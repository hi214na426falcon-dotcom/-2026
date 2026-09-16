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


def _cmd_analyze(args: argparse.Namespace) -> int:
    """アルパカ式の判定レポート(§16)を出力する。"""
    from .strategy.alpaca import AlpacaEngine

    config = load_strategy(args.config)
    if config.strategy_type != "alpaca_scoring":
        print("analyze は type=alpaca_scoring の戦略にのみ対応しています。")
        return 2
    if args.csv:
        candles = load_candles_csv(args.csv)
    else:
        candles = cyclical_feed(n=args.n, seed=args.seed)
        print(f"(--csv 未指定のため合成データ {len(candles)} 本で判定)\n")

    eng = AlpacaEngine(config, candles)
    idx = args.index if args.index is not None else len(candles) - 1
    if idx < eng.warmup:
        print(f"index={idx} は warmup({eng.warmup}) 未満です。より後方の足を指定してください。")
        return 2
    d = eng.decide(idx)

    label = {"HIGH": "▲ HIGH", "LOW": "▼ LOW", "SKIP": "― 見送り"}[d.signal]
    print(f"=== アルパカ式 判定レポート (index={idx}) ===")
    print(f"① 上位足        : {d.htf_trend}")
    print(f"② 高値安値/構造 : {d.trend} (強度 {d.trend_strength}/3)")
    print(f"③ ベースライン  : {d.baseline}  乖離 {d.deviation_atr} ATR")
    print(f"④ サポレジ      : S={d.support}  R={d.resistance}")
    print(f"⑤ ノイズ判定    : {d.noise}")
    print(f"⑥ スコア        : HIGH+{d.high_score} / LOW+{d.low_score} / net {d.net_score}")
    print(f"⑦ 根拠          : " + ("; ".join(d.reasons) if d.reasons else "-"))
    print(f"⑧ 判定          : {label}")
    print(f"⑨ 確信度        : {d.confidence}% (確率保証ではない)")
    print(f"⑪ 撤回条件      : " + ("; ".join(d.invalidation_conditions) or "-"))
    if args.json:
        Path(args.json).write_text(
            json.dumps(d.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n判定JSON 出力: {args.json}")
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

    a = sub.add_parser("analyze", help="アルパカ式の判定レポート(§16)を出力")
    a.add_argument("config")
    a.add_argument("--csv", default=None)
    a.add_argument("--index", type=int, default=None, help="判定する足(既定は最終足)")
    a.add_argument("--n", type=int, default=400)
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--json", default=None, help="判定JSONを出力")
    a.set_defaults(func=_cmd_analyze)

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
