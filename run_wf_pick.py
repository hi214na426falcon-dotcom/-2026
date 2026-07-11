#!/usr/bin/env python3
"""ウォークフォワードで生き残った選択ルールの「現在のピック」を出す。

ルール（backtest/walkforward.py と同一・事前登録）:
- 直近84日の実データで 96アーム × 4スロット+全帯 の勝率Wilson下限(95%)を計算
- 学習取引数 >= 150 のアームのうち下限が最大のものを選ぶ
- 下限が損益分岐（1/payout）を超えない場合は「見送り」＝打たない

これは占いではなく「直近84日で統計的に最も確からしかった設定」の機械的選択。
ウォークフォワード検証でのこのルールのOOS実績は runbook を参照
（JPYクロス夜間で勝率53〜55%、ペイアウト1.90でEV微プラス、1.80では負け）。

使い方:  python3 run_wf_pick.py [PAIR ...]     （既定 CHFJPY USDJPY AUDJPY）
"""
import sys
from datetime import datetime, timedelta, timezone

from backtest.data import Series, load_csv
from backtest.engine import run_backtest
from backtest.strategies import DOWN, UP, STRATEGIES
from backtest.walkforward import SLOTS_JST, build_grid, slot_index_jst
from run_walkforward_analysis import wilson_lcb, BREAKEVEN_190, MIN_TRAIN
from agents.pair_stats import find_pair_files

TRAIN_DAYS = 84


def pick(pair: str, data_dir: str = "data/m1"):
    files = find_pair_files(pair, data_dir)
    if not files:
        print(f"[{pair}] 実データなし")
        return
    bars = []
    for f in files:
        bars.extend(load_csv(f, name=pair).bars)
    series = Series(bars, name=pair)
    last = datetime.fromisoformat(series.bars[-1].time)
    t_from = last - timedelta(days=TRAIN_DAYS)

    best = None
    cache = {}
    for cfg in build_grid():
        key = f"{cfg['strategy']}|{sorted(cfg['params'].items())}"
        if key not in cache:
            cache[key] = STRATEGIES[cfg["strategy"]](series, **cfg["params"])
        sig = cache[key]
        if cfg["invert"]:
            sig = [UP if s == DOWN else DOWN if s == UP else None for s in sig]
        res = run_backtest(series, sig, payout=1.90, expiry_bars=cfg["expiry"],
                           stake=1000.0, start_balance=1e9, tie_policy="loss",
                           no_overlap=True, name=pair)
        per_slot = {i: [0, 0] for i in range(len(SLOTS_JST))}
        for t in res.trades:
            if t.time is None or datetime.fromisoformat(t.time) < t_from:
                continue
            si = slot_index_jst(t.time)
            if si is None:
                continue
            per_slot[si][0] += 1
            per_slot[si][1] += t.result == "win"
        views = list(per_slot.items()) + [
            ("all", [sum(v[0] for v in per_slot.values()),
                     sum(v[1] for v in per_slot.values())])]
        for slot, (n, w) in views:
            if n < MIN_TRAIN:
                continue
            lcb = wilson_lcb(w, n)
            if best is None or lcb > best[0]:
                label = (SLOTS_JST[slot] if isinstance(slot, int) else "全夜間")
                best = (lcb, w / n, n, cfg, label)

    print(f"\n===== {pair}（データ末尾 {last.date()}, 直近{TRAIN_DAYS}日で選択）=====")
    if best is None:
        print("  学習取引数が足りるアームがありません")
        return
    lcb, wr, n, cfg, slot = best
    print(f"  最良アーム: {cfg['strategy']} {cfg['params']}"
          f"{'（逆張り反転）' if cfg['invert'] else ''} 判定{cfg['expiry']}分"
          f" / JST時間帯 {slot}")
    print(f"  直近84日: 勝率 {wr*100:.2f}% (N={n}, Wilson下限 {lcb*100:.2f}%)")
    if lcb > BREAKEVEN_190:
        print(f"  → 下限が損益分岐52.63%を超過。ルール上は【採用】"
              f"（ただし期待勝率は53〜55%域。1.80倍では打たないこと）")
    else:
        print(f"  → 下限が損益分岐に届かず。ルール上は【見送り】＝今は打たない")


def main() -> int:
    pairs = [a.upper() for a in sys.argv[1:]] or ["CHFJPY", "USDJPY", "AUDJPY"]
    print("ウォークフォワード生存ルールによる現在ピック"
          "（データが古い場合は fetch-histdata.yml で更新してから実行）")
    for p in pairs:
        pick(p)
    print("\n※これは統計的選択であり将来の勝率を保証しない。デモでのフォワード"
          "テスト→少額、ペイアウト1.90以上の時間帯・商品に限定、資金管理は"
          "1,000円固定＋3連勝ボーナスのまま変えないこと。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
