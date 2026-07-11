#!/usr/bin/env python3
"""ウォークフォワード結果の集計 — 選択後のOOS成績だけを採点する。

backtest/walkforward.py が生成した results/wf/<PAIR>.json.gz を読み、
以下の**事前登録した選択方針**を全て並記で評価する（結果を見てから方針を
選ぶのは選択バイアスなので、必ず全方針を同時に報告する）:

- P1a: ペア内で学習窓のWilson下限が最大のアームを常に採用
- P1b: 同上だが、下限が損益分岐(52.63%@1.90)を超えた期間のみ取引（見送りあり）
- P2a/P2b: 全ペア横断で同じ選択
- P3 : 全ペア横断の上位3アームに分散

学習窓 = 直前6期間(84日) / 検定窓 = 次の14日。検定側の数字だけを合算する。
"""

from __future__ import annotations

import glob
import gzip
import json
import math
import os
import sys
from collections import defaultdict

BREAKEVEN_190 = 1 / 1.90   # 52.63%
BREAKEVEN_180 = 1 / 1.80   # 55.56%
MIN_TRAIN = 150
Z = 1.96


def wilson_lcb(w: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = w / n
    z2 = Z * Z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    rad = Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (centre - rad) / denom


def wilson_ci(w: int, n: int):
    if n == 0:
        return (0.0, 1.0)
    p = w / n
    z2 = Z * Z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    rad = Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return ((centre - rad) / denom, (centre + rad) / denom)


def load_all(wf_dir: str):
    arms = []   # dict: pair, label, per-period [n, w]
    period_starts = None
    for path in sorted(glob.glob(os.path.join(wf_dir, "*.json.gz"))):
        d = json.load(gzip.open(path, "rt"))
        if period_starts is None:
            period_starts = d["period_starts"]
        elif d["period_starts"] != period_starts:
            raise ValueError(f"期間グリッド不一致: {path}")
        slots = d["slots"] + ["all"]
        for gi, cfg in enumerate(d["grid"]):
            per_slot = d["counts"][gi]
            n_p = len(period_starts)
            allp = [[sum(per_slot[s][p][0] for s in range(4)),
                     sum(per_slot[s][p][1] for s in range(4))]
                    for p in range(n_p)]
            for si, slot in enumerate(slots):
                periods = per_slot[si] if si < 4 else allp
                label = (f"{cfg['strategy']}{cfg['params']}"
                         f"{'/逆' if cfg['invert'] else ''}/exp{cfg['expiry']}"
                         f"/{slot}")
                arms.append({"pair": d["pair"], "cfg": cfg, "slot": slot,
                             "label": label, "periods": periods})
    return arms, period_starts, d["train_periods"]


def evaluate_policy(arms, n_periods, train_periods, per_pair=None,
                    conditional=False, top_k=1):
    """各検定期間で学習窓最良アームを選び、検定側の成績を合算。"""
    pool = [a for a in arms if per_pair is None or a["pair"] == per_pair]
    N = W = 0
    traded_periods = 0
    picks = []
    yearly = defaultdict(lambda: [0, 0])
    for p in range(train_periods, n_periods):
        scored = []
        for a in pool:
            n_tr = sum(a["periods"][q][0] for q in range(p - train_periods, p))
            w_tr = sum(a["periods"][q][1] for q in range(p - train_periods, p))
            if n_tr < MIN_TRAIN:
                continue
            scored.append((wilson_lcb(w_tr, n_tr), a))
        if not scored:
            continue
        scored.sort(key=lambda x: -x[0])
        chosen = scored[:top_k]
        if conditional:
            chosen = [c for c in chosen if c[0] > BREAKEVEN_190]
        if not chosen:
            continue
        traded_periods += 1
        for lcb, a in chosen:
            n_te, w_te = a["periods"][p]
            N += n_te
            W += w_te
            year = 2023 + (p * 14 + 275) // 365  # 期間開始のおおよその年
            yearly[year][0] += n_te
            yearly[year][1] += w_te
            picks.append((p, a["pair"], a["label"], round(lcb * 100, 2),
                          n_te, w_te))
    return {"N": N, "W": W, "traded_periods": traded_periods,
            "picks": picks, "yearly": dict(yearly)}


def report(name, r, n_test_periods):
    N, W = r["N"], r["W"]
    if N == 0:
        print(f"{name:34s} 取引なし")
        return
    wr = W / N
    lo, hi = wilson_ci(W, N)
    ev19 = (wr * 0.90 - (1 - wr)) * 1000
    ev18 = (wr * 0.80 - (1 - wr)) * 1000
    print(f"{name:34s} OOS勝率 {wr*100:5.2f}% (95%CI {lo*100:.2f}〜{hi*100:.2f})"
          f"  N={N:,}  EV@1.90 {ev19:+.0f}円  EV@1.80 {ev18:+.0f}円"
          f"  取引期間 {r['traded_periods']}/{n_test_periods}")


def main() -> int:
    wf_dir = sys.argv[1] if len(sys.argv) > 1 else "results/wf"
    arms, period_starts, train_periods = load_all(wf_dir)
    n_p = len(period_starts)
    n_test = n_p - train_periods
    pairs = sorted({a["pair"] for a in arms})
    print(f"アーム総数 {len(arms):,}（{len(pairs)}ペア × 96設定 × 5スロット）"
          f" / 検定期間 {n_test} 個 × 14日\n")

    # 「必ずどこかにある」の実態: 全期間一括(インサンプル)で55%超のアーム数
    dredge = 0
    best_in = None
    for a in arms:
        n = sum(x[0] for x in a["periods"])
        w = sum(x[1] for x in a["periods"])
        if n >= 1000 and w / n >= 0.55:
            dredge += 1
        if n >= 1000 and (best_in is None or w / n > best_in[0]):
            best_in = (w / n, n, a["pair"], a["label"])
    print(f"[インサンプル漁り] 全期間一括で勝率55%以上のアーム: {dredge} 本 / "
          f"{len(arms):,} 本中")
    if best_in:
        print(f"[インサンプル最良] {best_in[2]} {best_in[3]} "
              f"勝率 {best_in[0]*100:.2f}% (N={best_in[1]:,})"
              f" ← これがOOSで再現するかがウォークフォワードの答え\n")

    print("=== ウォークフォワード成績（検定側のみの合算・事前登録方針を全て並記）===")
    r = evaluate_policy(arms, n_p, train_periods)
    report("P2a 全ペア横断・常時採用", r, n_test)
    r2b = evaluate_policy(arms, n_p, train_periods, conditional=True)
    report("P2b 全ペア横断・LCB>損益分岐のみ", r2b, n_test)
    r3 = evaluate_policy(arms, n_p, train_periods, top_k=3)
    report("P3  全ペア横断・上位3分散", r3, n_test)
    print()
    for pair in pairs:
        rp = evaluate_policy(arms, n_p, train_periods, per_pair=pair)
        report(f"P1a {pair} 常時採用", rp, n_test)
    print()
    for pair in pairs:
        rp = evaluate_policy(arms, n_p, train_periods, per_pair=pair,
                             conditional=True)
        report(f"P1b {pair} LCB>損益分岐のみ", rp, n_test)

    print("\n=== P2b の年別安定性 ===")
    for y, (n, w) in sorted(r2b["yearly"].items()):
        if n:
            print(f"  {y}: 勝率 {w/n*100:5.2f}%  N={n:,}")
    print("\n=== P2b が実際に選んだアーム（直近10期間）===")
    for p, pair, label, lcb, n_te, w_te in r2b["picks"][-10:]:
        print(f"  期間{p:3d} [{period_starts[p][:10]}] {pair} {label} "
              f"(学習LCB {lcb}%) → 検定 {w_te}/{n_te}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
