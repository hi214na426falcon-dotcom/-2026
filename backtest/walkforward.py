"""ウォークフォワード検証 — 「過去に最良だった設定を選び、次の期間だけで採点」を
3年間繰り返し、選択後のアウトオブサンプル成績だけを集計するための素材を作る。

設計（事前登録。結果を見てからグリッドを弄らないこと）:
- アーム = 戦略×パラメータ×順張り/逆張り×判定足数(1/3/5分) = 96通り
- 時間帯 = JST 17-20 / 20-24 / 0-3 / 3-6 の4スロット（JST6時台は除外）
- 期間 = 14日刻み。学習窓 = 直前6期間(84日)、検定窓 = 次の1期間(14日)
- 本モジュールは全アーム×スロット×期間の [取引数, 勝ち数] だけを出力する。
  どの選択方針でも後段（run_walkforward_analysis.py）で未来を見ずに再現できる。

勝敗ラベルはペイアウトに依存しないため、EV は分析側で 1.90/1.80 の両方を評価する。
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Series, load_csv
from .engine import run_backtest
from .strategies import DOWN, UP, STRATEGIES

SLOTS_JST: Tuple[Tuple[int, int], ...] = ((17, 20), (20, 24), (0, 3), (3, 6))
PERIOD_DAYS = 14
TRAIN_PERIODS = 6  # 学習窓 = 直前6期間 = 84日
FIRST_TEST = datetime(2023, 10, 2, tzinfo=timezone.utc)  # 先頭84日+αは学習専用


def build_grid() -> List[Dict]:
    """事前登録のアーム一覧。順序は決定論的。"""
    base: List[Tuple[str, Dict]] = []
    for period in (10, 20, 30):
        for num_std in (1.5, 2.0, 2.5):
            base.append(("bollinger", {"period": period, "num_std": num_std}))
    for period in (7, 14):
        for lo, hi in ((30.0, 70.0), (20.0, 80.0)):
            base.append(("rsi", {"period": period, "oversold": lo,
                                 "overbought": hi}))
    for fast, slow in ((5, 20), (10, 50)):
        base.append(("ma_cross", {"fast": fast, "slow": slow}))
    base.append(("macd", {}))
    grid: List[Dict] = []
    for strat, params in base:
        for invert in (False, True):
            for expiry in (1, 3, 5):
                grid.append({"strategy": strat, "params": params,
                             "invert": invert, "expiry": expiry})
    return grid


def slot_index_jst(iso_time: str) -> Optional[int]:
    """取引時刻(UTC ISO)→JSTスロット番号。JST6時台などスロット外は None。"""
    t = datetime.fromisoformat(iso_time)
    h = (t.hour + 9) % 24
    for i, (a, b) in enumerate(SLOTS_JST):
        if a <= h < b:
            return i
    return None


def period_starts_for(series: Series) -> List[datetime]:
    last = datetime.fromisoformat(series.bars[-1].time)
    starts = []
    cur = FIRST_TEST
    while cur + timedelta(days=PERIOD_DAYS) <= last + timedelta(days=1):
        starts.append(cur)
        cur += timedelta(days=PERIOD_DAYS)
    return starts


def run_pair(pair: str, data_dir: str = "data/m1") -> Dict:
    from agents.pair_stats import find_pair_files
    files = find_pair_files(pair, data_dir)
    if not files:
        raise FileNotFoundError(f"{pair} の実データが {data_dir} にありません")
    bars = []
    for f in files:
        bars.extend(load_csv(f, name=pair).bars)
    series = Series(bars, name=pair)

    grid = build_grid()
    starts = period_starts_for(series)
    start_ts = [s.timestamp() for s in starts]
    n_p = len(starts)
    counts = []  # [arm][slot][period] = [n, w]
    signal_cache: Dict[str, List] = {}
    for gi, cfg in enumerate(grid):
        key = f"{cfg['strategy']}|{sorted(cfg['params'].items())}"
        if key not in signal_cache:
            signal_cache[key] = STRATEGIES[cfg["strategy"]](series, **cfg["params"])
        signals = signal_cache[key]
        if cfg["invert"]:
            signals = [UP if s == DOWN else DOWN if s == UP else None
                       for s in signals]
        res = run_backtest(series, signals, payout=1.90,
                           expiry_bars=cfg["expiry"], stake=1000.0,
                           start_balance=1e9,  # 破産による打ち切りを防ぎ全取引を数える
                           tie_policy="loss", no_overlap=True, name=pair)
        arm = [[[0, 0] for _ in range(n_p)] for _ in SLOTS_JST]
        for t in res.trades:
            if t.time is None:
                continue
            si = slot_index_jst(t.time)
            if si is None:
                continue
            ts = datetime.fromisoformat(t.time).timestamp()
            pi = bisect_right(start_ts, ts) - 1
            if pi < 0 or pi >= n_p:
                continue
            arm[si][pi][0] += 1
            if t.result == "win":
                arm[si][pi][1] += 1
        counts.append(arm)
        print(f"  [{pair}] arm {gi+1}/{len(grid)} 完了", flush=True)
    return {
        "pair": pair,
        "grid": grid,
        "slots": [list(s) for s in SLOTS_JST],
        "period_days": PERIOD_DAYS,
        "train_periods": TRAIN_PERIODS,
        "period_starts": [s.isoformat() for s in starts],
        "counts": counts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ウォークフォワード素材の生成")
    p.add_argument("--pair", required=True)
    p.add_argument("--data-dir", default="data/m1")
    p.add_argument("--out", help="出力 json.gz（既定 results/wf/<PAIR>.json.gz）")
    args = p.parse_args(argv)
    out = args.out or os.path.join("results", "wf", f"{args.pair.upper()}.json.gz")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    data = run_pair(args.pair.upper(), args.data_dir)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    total = sum(c[0] for arm in data["counts"] for slot in arm for c in slot)
    print(f"[OUT] {out}  期間数={len(data['period_starts'])} "
          f"アーム={len(data['grid'])} 総取引={total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
