"""合格戦略の昇格ゲート — approved_strategy.json を「合格時のみ」生成する。

MASTER_PROMPT の合格基準（OOS で判定）:
- 損益分岐勝率 + 2pt 以上（edge_pt >= 2.0）
- サンプル 1,000 回以上
- 最大ドローダウンが資金の 20% 以内

★ 基準を満たさなければファイルを **書かない**。「惜しいから」とパラメータを
   いじって再判定するのはカーブフィッティングのため禁止（MASTER_PROMPT）。
   合格した時だけ approved_strategy.json ができ、予測サーバーが方向配信を始める。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Series, generate_synthetic, load_csv
from .engine import run_backtest
from .sessions import MASTER_SESSIONS_JST, restrict_signals_to_sessions
from .strategies import STRATEGIES

# 合格基準
EDGE_GATE_PT = 2.0
MIN_TRADES = 1000
MAX_DD_GATE = 0.20


def metrics_from_trades(trades, payout: float, stake: float,
                        start_balance: float) -> Dict[str, float]:
    """トレード列から勝率・エッジ・最大DDを（残高曲線を再構築して）計算する。"""
    wins = sum(1 for t in trades if t.result == "win")
    losses = sum(1 for t in trades if t.result == "loss")
    decided = wins + losses
    win_rate = wins / decided if decided else 0.0
    breakeven = 1.0 / payout
    balance = start_balance
    peak = balance
    max_dd_pct = 0.0
    for t in trades:
        if t.result == "win":
            balance += stake * (payout - 1.0)
        elif t.result == "loss":
            balance -= stake
        if balance > peak:
            peak = balance
        if peak > 0:
            dd = (peak - balance) / peak
            if dd > max_dd_pct:
                max_dd_pct = dd
    return {
        "trades": float(decided),
        "win_rate": win_rate,
        "edge_pt": (win_rate - breakeven) * 100.0,
        "breakeven": breakeven,
        "max_dd_pct": max_dd_pct,
        "total_pnl": balance - start_balance,
    }


def evaluate(
    pair: str,
    strategy: str,
    params: Optional[dict] = None,
    expiry_min: int = 3,
    payout: float = 1.90,
    data_dir: str = "data/m1",
    oos_frac: float = 0.6,
    sessions: Sequence[Tuple[int, int]] = tuple(MASTER_SESSIONS_JST),
    tz_offset_hours: int = 9,
    stake: float = 1000.0,
    start_balance: float = 100000.0,
    process: str = "randomwalk",
) -> Dict:
    """IS/OOS 分割で評価し、OOS 成績と合否を返す（ファイルは書かない）。"""
    if strategy not in STRATEGIES:
        raise ValueError(f"未知の戦略: {strategy}")
    # データ
    from agents.pair_stats import find_pair_files  # 循環回避のため遅延 import
    files = find_pair_files(pair, data_dir)
    if files:
        bars = []
        for f in files:
            bars.extend(load_csv(f, name=pair).bars)
        series = Series(bars, name=pair)
        is_synthetic = False
    else:
        series = generate_synthetic(n=8000, seed=100 + sum(ord(c) for c in pair),
                                    process=process, bar_minutes=1)
        series.name = pair
        is_synthetic = True

    fn = STRATEGIES[strategy]
    signals = fn(series, seed=0) if strategy == "random" else fn(series, **(params or {}))
    times = [b.time for b in series.bars]
    signals = restrict_signals_to_sessions(times, signals, sessions, tz_offset_hours)

    res = run_backtest(series, signals, payout=payout, expiry_bars=expiry_min,
                       stake=stake, start_balance=start_balance, no_overlap=True, name=pair)
    n = len(series)
    split = int(n * oos_frac)
    oos_trades = [t for t in res.trades if t.index >= split]
    m = metrics_from_trades(oos_trades, payout, stake, start_balance)

    passed = (
        m["edge_pt"] >= EDGE_GATE_PT
        and m["trades"] >= MIN_TRADES
        and m["max_dd_pct"] <= MAX_DD_GATE
        and not is_synthetic  # 合成データは決して合格にしない
    )
    reasons = []
    if is_synthetic:
        reasons.append("合成データ（実データではない）")
    if m["edge_pt"] < EDGE_GATE_PT:
        reasons.append(f"エッジ不足 {m['edge_pt']:+.2f}pt < +{EDGE_GATE_PT}pt")
    if m["trades"] < MIN_TRADES:
        reasons.append(f"サンプル不足 {int(m['trades'])} < {MIN_TRADES}")
    if m["max_dd_pct"] > MAX_DD_GATE:
        reasons.append(f"DD超過 {m['max_dd_pct']*100:.1f}% > {MAX_DD_GATE*100:.0f}%")

    return {
        "pair": pair,
        "strategy": strategy,
        "params": params or {},
        "expiry_min": expiry_min,
        "payout": payout,
        "sessions_jst": [list(s) for s in sessions],
        "tz_offset_hours": tz_offset_hours,
        "oos": {
            "win_rate": round(m["win_rate"], 4),
            "edge_pt": round(m["edge_pt"], 2),
            "trades": int(m["trades"]),
            "max_dd_pct": round(m["max_dd_pct"], 4),
        },
        "oos_passed": bool(passed),
        "reasons": reasons,
        "is_synthetic": is_synthetic,
        "data_source": files[0] if files else f"synthetic:{process}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def promote(evaluation: Dict, out_path: str) -> bool:
    """合格していれば approved_strategy.json を書く。書いたら True。"""
    if not evaluation.get("oos_passed"):
        return False
    approved = {k: evaluation[k] for k in (
        "pair", "strategy", "params", "expiry_min", "payout",
        "sessions_jst", "tz_offset_hours", "oos", "oos_passed",
        "is_synthetic", "data_source", "generated_at")}
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(approved, f, ensure_ascii=False, indent=2)
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="合格戦略の昇格ゲート")
    p.add_argument("--pair", required=True)
    p.add_argument("--strategy", default="bollinger")
    p.add_argument("--period", type=int)
    p.add_argument("--num-std", type=float)
    p.add_argument("--expiry", type=int, default=3)
    p.add_argument("--payout", type=float, default=1.90)
    p.add_argument("--data-dir", default="data/m1")
    p.add_argument("--process", default="randomwalk",
                   choices=["randomwalk", "meanrevert", "trend"])
    p.add_argument("--out", default=os.path.join("backtest", "results", "approved_strategy.json"))
    args = p.parse_args(argv)

    params = {}
    if args.period is not None:
        params["period"] = args.period
    if args.num_std is not None:
        params["num_std"] = args.num_std

    ev = evaluate(args.pair, args.strategy, params=params, expiry_min=args.expiry,
                  payout=args.payout, data_dir=args.data_dir, process=args.process)
    o = ev["oos"]
    print(f"[評価] {ev['pair']} {ev['strategy']} params={ev['params']} "
          f"expiry={ev['expiry_min']}分 payout={ev['payout']}")
    print(f"  データ: {ev['data_source']}"
          f"{'（合成・合格対象外）' if ev['is_synthetic'] else ''}")
    print(f"  OOS成績: 勝率 {o['win_rate']*100:.2f}%  エッジ {o['edge_pt']:+.2f}pt  "
          f"サンプル {o['trades']}件  最大DD {o['max_dd_pct']*100:.1f}%")
    print(f"  合格基準: エッジ>=+{EDGE_GATE_PT}pt / サンプル>={MIN_TRADES} / DD<={MAX_DD_GATE*100:.0f}%")
    if ev["oos_passed"]:
        promote(ev, args.out)
        print(f"  → ★合格★ approved_strategy.json を書き出しました: {args.out}")
        print("     予測サーバーが方向配信を開始します（デモ→最小額から）。")
    else:
        print(f"  → 不合格。理由: {', '.join(ev['reasons'])}")
        print("     approved_strategy.json は作成しません（方向は非表示のまま）。")
        print("     ※パラメータを弄って再判定しないこと＝カーブフィッティング防止。")
    return 0 if ev["oos_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
