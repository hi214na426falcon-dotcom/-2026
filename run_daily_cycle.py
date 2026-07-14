#!/usr/bin/env python3
"""日次アダプティブ運用 — 毎朝の評価＋その日の有望ペア選抜。

毎朝(JST 6時)の想定処理:
1. 【評価】paper_log.jsonl から前日ぶん＋累計の成績を集計（日次・ペア別・Wilson CI）。
2. 【選抜】自動紙上取引が可能な暗号資産(BTC/ETH)を、直近84日のウォークフォワード
   下限(Wilson LCB)で機械的にランク付けし、損益分岐(1/payout)を超えるものだけを
   「本日の対象」に選ぶ。超えるものが無ければ最上位1本を⚠付きで様子見選抜。
   → results/paper/today_pairs.json を書き出す（run_paper_forward.py が参照）。

★ 選抜は「昨日負けたから外す」ではなく直近実測に基づく決定論。恣意的な弄りはしない
   （＝カーブフィッティング防止）。コード修正が要るのは壊れている時だけ。

使い方: python3 run_daily_cycle.py [--emit]   （--emit で today_pairs.json を書く）
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

LOG_PATH = os.path.join("results", "paper", "paper_log.jsonl")
TODAY_PATH = os.path.join("results", "paper", "today_pairs.json")
CRYPTO = ["BTCUSD", "ETHUSD"]
PAYOUT = 1.90
BREAKEVEN = 1.0 / PAYOUT  # 52.63%


def wilson(w, n):
    if not n:
        return (0.0, 0.0)
    z = 1.96
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return ((c - r) * 100, (c + r) * 100)


def load_log():
    rows = []
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def evaluate(rows):
    today_jst = (datetime.now(timezone.utc) + timedelta(hours=9)).date()
    yday = (today_jst - timedelta(days=1)).isoformat()
    print(f"=== 評価 {today_jst.isoformat()} 朝 ===")
    # 前日
    yr = [r for r in rows if r.get("day") == yday]
    if yr:
        n = len(yr); w = sum(1 for r in yr if r["result"] == "win")
        pnl = sum(r["pnl"] for r in yr)
        print(f"[前日 {yday}] {n}戦 {w}勝{n-w}敗 勝率{w/n*100:.1f}% 損益{pnl:+,.0f}円")
        by = defaultdict(lambda: [0, 0, 0.0])
        for r in yr:
            by[r["pair"]][0] += 1; by[r["pair"]][1] += r["result"] == "win"
            by[r["pair"]][2] += r["pnl"]
        for p, (n2, w2, pl) in by.items():
            print(f"   {p}: {n2}戦 {w2}勝 勝率{w2/n2*100:.0f}% 損益{pl:+,.0f}円")
    else:
        print(f"[前日 {yday}] 取引なし")
    # 累計
    if rows:
        n = len(rows); w = sum(1 for r in rows if r["result"] == "win")
        pnl = sum(r["pnl"] for r in rows)
        lo, hi = wilson(w, n)
        print(f"[累計] {n}戦 勝率{w/n*100:.1f}%(CI {lo:.1f}-{hi:.1f}) "
              f"損益{pnl:+,.0f}円 損益分岐{BREAKEVEN*100:.1f}%")
    return today_jst


def rank_and_select(emit):
    """BTC/ETH を直近84日WF下限でランク付けし today_pairs を決める。"""
    from run_wf_pick import pick as wf_pick
    ranked = []
    for pair in CRYPTO:
        info = wf_pick(pair, min_expiry=3)  # 内部で84日窓の最良アーム＋LCBを出力
        if info:
            ranked.append(info)
    ranked.sort(key=lambda x: -x["train"]["lcb"])
    chosen = [x for x in ranked if x["train"]["lcb"] > BREAKEVEN]
    watch = False
    if not chosen and ranked:
        chosen = ranked[:1]      # 全滅時は最上位1本だけ様子見
        watch = True
    print("\n=== 本日の選抜（直近84日WF下限で決定）===")
    for x in ranked:
        mark = "◎採用" if x in chosen and not watch else ("△様子見" if x in chosen else "×見送り")
        print(f"  {x['pair']}: 下限{x['train']['lcb']*100:.1f}% "
              f"(84日勝率{x['train']['win_rate']*100:.1f}%,N={x['train']['n']}) {mark}")
    pairs = [x["pair"] for x in chosen]
    payload = {
        "date": (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat(),
        "pairs": pairs,
        "watch_only": watch,
        "rationale": "直近84日ウォークフォワード下限が損益分岐超のペアのみ採用"
                     + ("（全滅のため最上位1本を様子見選抜）" if watch else ""),
        "ranked": [{"pair": x["pair"], "lcb": round(x["train"]["lcb"], 4),
                    "expiry_min": x["expiry_min"], "params": x["params"]}
                   for x in ranked],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if emit:
        os.makedirs(os.path.dirname(TODAY_PATH), exist_ok=True)
        with open(TODAY_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n[EMIT] {TODAY_PATH} → 本日の対象: {pairs or '（なし＝今日は打たない）'}")
    return payload


def main() -> int:
    emit = "--emit" in sys.argv[1:]
    rows = load_log()
    evaluate(rows)
    rank_and_select(emit)
    print("\n※選抜は直近実測に基づく決定論。勝率は将来を保証しない。"
          "ペイアウト1.90以上のみ・1,000円固定・複数週で判断。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
