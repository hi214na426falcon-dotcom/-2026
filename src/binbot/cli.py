"""コマンドラインインターフェース.

例:
  python -m binbot gen-data --kind ou --n 20000 --out data/sample_ou_m1.csv
  python -m binbot backtest --synth ou --strategy mean_reversion --horizon 5 --payout 0.85
  python -m binbot backtest --data data/your_real_data.csv --strategy mean_reversion
  python -m binbot walkforward --synth ou --strategy mean_reversion
  python -m binbot papertrade --synth ou --strategy mean_reversion --max-steps 8000
  python -m binbot compare        # ou(平均回帰) と gbm(ランダム) で全戦略を正直に比較
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import data as D
from .backtest import BacktestConfig, backtest_strategy
from .walkforward import WFConfig, walk_forward
from .paper_trader import PaperConfig, run_paper
from .strategy import REGISTRY, get_strategy


def _load_prices(args) -> pd.DataFrame:
    if getattr(args, "data", None):
        return D.load_csv(args.data)
    kind = getattr(args, "synth", None) or "ou"
    return D.make_sample(kind=kind, n=getattr(args, "n", 20000), seed=getattr(args, "seed", 7))


def _bt_cfg(args) -> BacktestConfig:
    return BacktestConfig(horizon=args.horizon, payout=args.payout,
                          tie=args.tie, one_position=not args.allow_overlap)


def _add_common(sp):
    sp.add_argument("--data", help="実データCSVのパス (指定時は --synth を無視)")
    sp.add_argument("--synth", choices=["ou", "gbm"], default="ou",
                    help="合成データ種別 (ou=平均回帰 / gbm=ランダムウォーク)")
    sp.add_argument("--n", type=int, default=20000, help="合成データのバー数")
    sp.add_argument("--seed", type=int, default=7)
    sp.add_argument("--strategy", choices=list(REGISTRY), default="mean_reversion")
    sp.add_argument("--horizon", type=int, default=5, help="満期までのバー数")
    sp.add_argument("--payout", type=float, default=0.85, help="勝った時の倍率")
    sp.add_argument("--tie", choices=["loss", "push", "win"], default="loss")
    sp.add_argument("--allow-overlap", action="store_true", help="同時複数建玉を許可")


def cmd_gen_data(args):
    df = D.make_sample(kind=args.kind, n=args.n, seed=args.seed)
    D.save_csv(df, args.out)
    print(f"saved {len(df)} bars -> {args.out}  (kind={args.kind})")


def cmd_backtest(args):
    df = _load_prices(args)
    strat = get_strategy(args.strategy)
    trades, stats = backtest_strategy(df, strat, _bt_cfg(args))
    src = args.data if args.data else f"synth:{args.synth}"
    print(f"=== backtest  strategy={args.strategy}  data={src}  bars={len(df)} ===")
    print(stats.summary())
    _maybe_report(args, {"mode": "backtest", "strategy": args.strategy, "source": src,
                         "bars": len(df), "stats": stats.as_dict()}, trades)


def cmd_walkforward(args):
    df = _load_prices(args)
    cls = REGISTRY[args.strategy]
    wf = WFConfig(train_bars=args.train, test_bars=args.test, min_trades=args.min_trades)
    oos_trades, oos_stats, sel = walk_forward(df, cls, _bt_cfg(args), wf)
    src = args.data if args.data else f"synth:{args.synth}"
    print(f"=== walk-forward (OUT-OF-SAMPLE)  strategy={args.strategy}  data={src} ===")
    print(f"windows={len(sel)} train={args.train} test={args.test}")
    print(oos_stats.summary())
    print("\n[注意] これがオーバーフィットを除いた、最も現実に近い勝率です。")
    _maybe_report(args, {"mode": "walkforward", "strategy": args.strategy, "source": src,
                         "windows": sel, "stats": oos_stats.as_dict()}, oos_trades)


def cmd_papertrade(args):
    df = _load_prices(args)
    strat = get_strategy(args.strategy)
    pcfg = PaperConfig(stake=args.stake, risk_pct=args.risk_pct,
                       max_steps=args.max_steps, verbose=args.verbose)
    broker, trades, stats = run_paper(df, strat, _bt_cfg(args), pcfg, balance=args.balance)
    src = args.data if args.data else f"synth:{args.synth}"
    print(f"=== PAPER TRADE (demo, 実弾なし)  strategy={args.strategy}  data={src} ===")
    print(f"開始残高={args.balance:.0f}  最終残高={broker.get_balance():.0f}  "
          f"損益={broker.get_balance()-args.balance:+.1f}")
    print(stats.summary())
    _maybe_report(args, {"mode": "papertrade", "strategy": args.strategy, "source": src,
                         "start_balance": args.balance, "end_balance": broker.get_balance(),
                         "stats": stats.as_dict()}, trades)


def cmd_compare(args):
    """ou(平均回帰) と gbm(ランダム) で全戦略を回し、正直な対比を見せる."""
    bt = BacktestConfig(horizon=args.horizon, payout=args.payout)
    print(f"ペイアウト={args.payout:.0%} → 損益分岐勝率={1/(1+args.payout):.1%}  "
          f"(これを超えないと理論上は負け)\n")
    for kind in ("ou", "gbm"):
        label = "平均回帰あり (戦略が効くべき市場)" if kind == "ou" else "ランダムウォーク (エッジ無し市場)"
        df = D.make_sample(kind=kind, n=args.n, seed=args.seed)
        print(f"----- データ: {kind}  {label} -----")
        for name in REGISTRY:
            _, st = backtest_strategy(df, get_strategy(name), bt)
            lo, hi = st.win_rate_ci95
            tag = "○" if (st.n_trades and st.edge_vs_breakeven > 0) else "×"
            print(f"  {name:14s} 取引={st.n_trades:5d}  勝率={st.win_rate:6.1%} "
                  f"[{lo:.0%}-{hi:.0%}]  期待値={st.expectancy:+.4f} {tag}")
        print()
    print("読み方: gbm では誰がやっても勝率≒50%・期待値マイナス。ou では逆張りが")
    print("勝率を上げるが、それは『平均回帰が存在する』という前提のデモ。実市場が")
    print("そうである保証は無い → だから自分の実データで walkforward を回すこと。")


def _maybe_report(args, meta: dict, trades: pd.DataFrame):
    if not getattr(args, "report", None):
        return
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if len(trades):
        trades.to_csv(out.with_suffix(".trades.csv"), index=False)
    print(f"[report] -> {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="binbot", description="バイナリー バックテスト/ペーパートレード基盤")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen-data", help="合成データCSVを生成")
    g.add_argument("--kind", choices=["ou", "gbm"], default="ou")
    g.add_argument("--n", type=int, default=20000)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_gen_data)

    b = sub.add_parser("backtest", help="単一バックテスト")
    _add_common(b)
    b.add_argument("--report", help="結果JSONの出力先")
    b.set_defaults(func=cmd_backtest)

    w = sub.add_parser("walkforward", help="アウトオブサンプル検証")
    _add_common(w)
    w.add_argument("--train", type=int, default=6000)
    w.add_argument("--test", type=int, default=2000)
    w.add_argument("--min-trades", type=int, default=25)
    w.add_argument("--report")
    w.set_defaults(func=cmd_walkforward)

    pt = sub.add_parser("papertrade", help="デモ自動売買 (実弾なし)")
    _add_common(pt)
    pt.add_argument("--balance", type=float, default=100000.0)
    pt.add_argument("--stake", type=float, default=1.0)
    pt.add_argument("--risk-pct", type=float, default=0.0)
    pt.add_argument("--max-steps", type=int, default=None)
    pt.add_argument("--verbose", action="store_true")
    pt.add_argument("--report")
    pt.set_defaults(func=cmd_papertrade)

    c = sub.add_parser("compare", help="ou/gbm × 全戦略の正直な比較")
    c.add_argument("--n", type=int, default=20000)
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--horizon", type=int, default=5)
    c.add_argument("--payout", type=float, default=0.85)
    c.set_defaults(func=cmd_compare)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
