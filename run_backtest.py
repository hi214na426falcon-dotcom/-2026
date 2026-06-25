#!/usr/bin/env python3
"""バイナリーオプション・バックテストの実行スクリプト（CLI）。

依存なし（Python 3.8+ 標準ライブラリのみ）。

使用例:
    # 既定: 合成データ(ランダムウォーク)で全戦略を比較 + 過剰最適化デモ
    python3 run_backtest.py

    # 実データ CSV を使う（ヘッダーに close または price 列が必要）
    python3 run_backtest.py --data path/to/USDJPY_M5.csv --strategy rsi

    # ペイアウト・判定足・投資額を変える
    python3 run_backtest.py --strategy bollinger --payout 1.90 --expiry 3 --stake 1000

    # 合成データの性質を変える（逆張りが有利な平均回帰系など）
    python3 run_backtest.py --process meanrevert --strategy rsi

    # 利用可能な戦略一覧
    python3 run_backtest.py --list-strategies
"""

from __future__ import annotations

import argparse
import sys

from backtest.data import generate_synthetic, load_csv
from backtest.engine import format_report, run_backtest
from backtest.optimize import format_optimize_report, optimize_rsi_demo
from backtest.strategies import STRATEGIES, strat_random


HONEST_FOOTER = """
------------------------------------------------------------------
【結果の読み方 — 正直な注意】
* 損益分岐勝率 = 1 / ペイアウト率。これを上回って初めて利益が出る。
  例) ペイアウト 1.85 → 54.1%、1.90 → 52.6%、2.00 → 50.0%。
* ランダム戦略はおおむね勝率 50% 付近に収まり、ペイアウト < 2.0 では
  必ず負け越す。「根拠のないエントリー」が損になることの証明。
* 合成データ(既定=ランダムウォーク)には本質的な優位性が無いよう作ってある。
  特定戦略が大勝ちしていたら、それは偶然（小サンプル）か過剰最適化を疑うこと。
* バックテストで高勝率が出ても、検証(out-of-sample)で崩れれば無意味。
  上の「過剰最適化の実証」を必ず参照。
* 実運用ではスプレッド・約定遅延・業者リスク（特に海外無登録業者）で
  成績はさらに悪化しうる。本ツールの数値は上限の目安と考えること。
* このツールは投資助言ではなく、戦略を“正直に”検証するための教材です。
------------------------------------------------------------------
""".strip()


def build_series(args) -> "object":
    if args.data:
        series = load_csv(args.data)
        print(f"[データ] CSV を読み込みました: {args.data} ({len(series)} 本)")
    else:
        series = generate_synthetic(
            n=args.bars,
            seed=args.seed,
            process=args.process,
            drift=args.drift,
            vol=args.vol,
        )
        print(
            f"[データ] 合成データを生成: process={args.process}, "
            f"{len(series)} 本, seed={args.seed}"
        )
    return series


def run_one(series, name, signals, args):
    res = run_backtest(
        series,
        signals,
        payout=args.payout,
        expiry_bars=args.expiry,
        stake=args.stake,
        start_balance=args.balance,
        tie_policy=args.tie,
        no_overlap=not args.allow_overlap,
        name=name,
    )
    print(format_report(res))
    print()
    return res


def make_signals(name, series, args):
    fn = STRATEGIES[name]
    if name == "random":
        return fn(series, seed=args.seed)
    return fn(series)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="バイナリーオプション(High/Low)バックテスター",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--data", help="OHLC の CSV パス（未指定なら合成データ）")
    p.add_argument(
        "--strategy",
        default="all",
        help="戦略名（既定 all = 全戦略を比較）。一覧は --list-strategies",
    )
    p.add_argument("--payout", type=float, default=1.85, help="ペイアウト率（既定 1.85）")
    p.add_argument("--expiry", type=int, default=1, help="判定までの足数（既定 1）")
    p.add_argument("--stake", type=float, default=1000.0, help="1取引の投資額（既定 1000）")
    p.add_argument("--balance", type=float, default=100000.0, help="初期残高（既定 100000）")
    p.add_argument(
        "--tie",
        choices=["loss", "refund", "win"],
        default="loss",
        help="同値判定の扱い（既定 loss=保守的）",
    )
    p.add_argument(
        "--allow-overlap",
        action="store_true",
        help="建玉中も新規シグナルを取る（既定は単一ポジション）",
    )
    # 合成データ用
    p.add_argument("--bars", type=int, default=3000, help="合成データの本数（既定 3000）")
    p.add_argument("--seed", type=int, default=42, help="乱数シード（既定 42）")
    p.add_argument(
        "--process",
        choices=["randomwalk", "meanrevert", "trend"],
        default="randomwalk",
        help="合成データの生成過程（既定 randomwalk）",
    )
    p.add_argument("--drift", type=float, default=0.0, help="合成データのドリフト")
    p.add_argument("--vol", type=float, default=0.0008, help="合成データのボラティリティ")
    p.add_argument(
        "--no-optimize",
        action="store_true",
        help="過剰最適化の実証デモを省略する",
    )
    p.add_argument(
        "--list-strategies", action="store_true", help="利用可能な戦略を表示して終了"
    )
    args = p.parse_args(argv)

    if args.list_strategies:
        print("利用可能な戦略:")
        for k in STRATEGIES:
            print(f"  - {k}")
        print("  - all (全戦略を比較)")
        return 0

    series = build_series(args)
    print(
        f"[設定] payout={args.payout}, expiry={args.expiry}本, "
        f"stake={args.stake:.0f}円, tie={args.tie}, "
        f"overlap={'許可' if args.allow_overlap else '禁止'}\n"
    )

    if args.strategy == "all":
        # ランダムを最初に表示（基準線）してから各戦略
        order = ["random"] + [k for k in STRATEGIES if k != "random"]
        for name in order:
            run_one(series, name, make_signals(name, series, args), args)
    else:
        if args.strategy not in STRATEGIES:
            print(f"未知の戦略: {args.strategy}", file=sys.stderr)
            print(f"利用可能: {', '.join(STRATEGIES)} / all", file=sys.stderr)
            return 2
        run_one(series, args.strategy, make_signals(args.strategy, series, args), args)

    if not args.no_optimize:
        print(
            format_optimize_report(
                optimize_rsi_demo(
                    series,
                    payout=args.payout,
                    expiry_bars=args.expiry,
                    stake=args.stake,
                )
            )
        )
        print()

    print(HONEST_FOOTER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
