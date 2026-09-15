"""コマンドラインインタフェース。

  python -m alpaca_clone.cli gen-data  out.csv [--n 1000] [--mode walk|cycle]
  python -m alpaca_clone.cli backtest  config/strategies/example_rsi_reversal.json \
      [--csv data.csv] [--balance 1000] [--stake 10]
  python -m alpaca_clone.cli serve     config/strategies/example_rsi_reversal.json \
      [--port 8787] [--tick 1.0] [--autostart]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .backtest.engine import Backtester
from .data.feed import SyntheticFeed, cyclical_feed, load_candles_csv
from .strategy.engine import load_strategy


def _cmd_gen_data(args: argparse.Namespace) -> int:
    if args.mode == "cycle":
        candles = cyclical_feed(n=args.n, seed=args.seed)
    else:
        candles = SyntheticFeed(n=args.n, seed=args.seed).candles()
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.timestamp, c.open, c.high, c.low, c.close, c.volume])
    print(f"生成: {args.out} ({len(candles)} 本, mode={args.mode})")
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    config = load_strategy(args.config)
    if args.csv:
        candles = load_candles_csv(args.csv)
    else:
        candles = cyclical_feed(n=args.n, seed=args.seed)
        print(f"(--csv 未指定のため合成データ {len(candles)} 本で検証)")

    bt = Backtester(config, starting_balance=args.balance,
                    stake=args.stake, stake_mode=args.stake_mode)
    result = bt.run(candles)
    summary = result.summary()

    print(f"\n=== バックテスト結果: {config.name} ===")
    for k, v in summary.items():
        print(f"  {k:24}: {v}")
    if summary["trades"]:
        be = summary["breakeven_win_rate"]
        wr = summary["win_rate"]
        verdict = "＋期待値プラス方向" if wr > be else "－損益分岐未満(この検証では不利)"
        print(f"\n  勝率 {wr:.1%} / 損益分岐 {be:.1%} → {verdict}")
    if args.json:
        Path(args.json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 出力: {args.json}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server.session import PaperSession
    from .server.app import serve

    config = load_strategy(args.config)
    source = load_candles_csv(args.csv) if args.csv else None
    session = PaperSession(
        config, stake=args.stake, stake_mode=args.stake_mode,
        starting_balance=args.balance, tick_interval=args.tick,
        source_candles=source,
    )
    serve(session, host=args.host, port=args.port, autostart=args.autostart)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="alpaca_clone",
                                description="バイナリー戦略の検証/ペーパー運用")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gen-data", help="検証用データを生成(CSV)")
    g.add_argument("out")
    g.add_argument("--n", type=int, default=1000)
    g.add_argument("--mode", choices=["walk", "cycle"], default="cycle")
    g.add_argument("--seed", type=int, default=7)
    g.set_defaults(func=_cmd_gen_data)

    b = sub.add_parser("backtest", help="過去データで戦略を検証")
    b.add_argument("config")
    b.add_argument("--csv", default=None)
    b.add_argument("--n", type=int, default=1000)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--balance", type=float, default=1000.0)
    b.add_argument("--stake", type=float, default=10.0)
    b.add_argument("--stake-mode", choices=["fixed", "percent"], default="fixed")
    b.add_argument("--json", default=None, help="結果を JSON 出力")
    b.set_defaults(func=_cmd_backtest)

    s = sub.add_parser("serve", help="ダッシュボードで常駐ペーパー運用")
    s.add_argument("config")
    s.add_argument("--csv", default=None, help="指定時はCSVをリプレイ、無指定は合成ライブ")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--tick", type=float, default=1.0, help="1足あたりの秒間隔")
    s.add_argument("--balance", type=float, default=1000.0)
    s.add_argument("--stake", type=float, default=10.0)
    s.add_argument("--stake-mode", choices=["fixed", "percent"], default="fixed")
    s.add_argument("--autostart", action="store_true")
    s.set_defaults(func=_cmd_serve)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
