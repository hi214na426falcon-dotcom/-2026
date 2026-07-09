"""「過剰最適化（カーブフィッティング）」を実証するモジュール。

手順:
1. データを学習区間(train)と検証区間(test)に時系列で分割する。
2. パラメータ格子(grid)を学習区間で総当たりし、最も勝率の高い設定を選ぶ。
3. その「優勝設定」を未知の検証区間に適用して成績を見る。

ほとんどの場合、train の勝率は高く見えても test では大きく落ちる。これは
「バックテストで高勝率が出た」ことが将来の成績を保証しない決定的な理由であり、
"勝率 80%" を狙ってパラメータを弄る行為が無意味（むしろ有害）であることを示す。
"""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Optional, Tuple

from .data import Series
from .engine import run_backtest
from .strategies import strat_rsi_reversal


def _winrate_and_pnl(
    series: Series,
    signals,
    payout: float,
    expiry_bars: int,
    stake: float,
) -> Tuple[float, float, int]:
    res = run_backtest(
        series,
        signals,
        payout=payout,
        expiry_bars=expiry_bars,
        stake=stake,
        no_overlap=True,
    )
    m = res.metrics()
    return m["win_rate"], m["total_pnl"], int(m["trades"])


def optimize_rsi_demo(
    series: Series,
    train_frac: float = 0.6,
    payout: float = 1.85,
    expiry_bars: int = 1,
    stake: float = 1000.0,
    min_trades: int = 30,
) -> Dict[str, object]:
    """RSI 逆張りのしきい値・期間を学習区間で最適化し、検証区間で評価する。"""
    n = len(series)
    split = int(n * train_frac)
    train = series.slice(0, split)
    test = series.slice(split, n)

    periods = [7, 14, 21]
    bands = [(20, 80), (25, 75), (30, 70), (35, 65), (40, 60)]

    best = None  # (train_winrate, params, train_stats)
    all_rows: List[Tuple] = []

    for period, (os_, ob) in product(periods, bands):
        sig_tr = strat_rsi_reversal(train, period=period, oversold=os_, overbought=ob)
        wr, pnl, ntr = _winrate_and_pnl(train, sig_tr, payout, expiry_bars, stake)
        all_rows.append((period, os_, ob, wr, pnl, ntr))
        if ntr < min_trades:
            continue
        if best is None or wr > best[0]:
            best = (wr, (period, os_, ob), (wr, pnl, ntr))

    if best is None:
        return {"error": "学習区間で最低取引回数を満たす設定がありませんでした。"}

    _, (bp, bos, bob), (tr_wr, tr_pnl, tr_n) = best
    sig_te = strat_rsi_reversal(test, period=bp, oversold=bos, overbought=bob)
    te_wr, te_pnl, te_n = _winrate_and_pnl(test, sig_te, payout, expiry_bars, stake)

    return {
        "split_index": split,
        "best_params": {"period": bp, "oversold": bos, "overbought": bob},
        "train": {"win_rate": tr_wr, "total_pnl": tr_pnl, "trades": tr_n},
        "test": {"win_rate": te_wr, "total_pnl": te_pnl, "trades": te_n},
        "breakeven_win_rate": 1.0 / payout,
        "grid_size": len(all_rows),
        "all_rows": all_rows,
    }


def format_optimize_report(r: Dict[str, object]) -> str:
    if "error" in r:
        return f"[最適化デモ] {r['error']}"
    bp = r["best_params"]
    tr = r["train"]
    te = r["test"]
    be = r["breakeven_win_rate"]
    drop = (tr["win_rate"] - te["win_rate"]) * 100
    lines = [
        "=== 過剰最適化（カーブフィッティング）の実証: RSI 逆張り ===",
        f"  探索したパラメータ組合せ : {r['grid_size']} 通り",
        f"  学習区間で選ばれた最良設定: period={bp['period']}, "
        f"oversold={bp['oversold']}, overbought={bp['overbought']}",
        f"  損益分岐勝率              : {be*100:.1f}%",
        "  ----------------------------------------------------------",
        f"  学習区間(train) 勝率      : {tr['win_rate']*100:.1f}%  "
        f"損益 {tr['total_pnl']:+,.0f} 円  ({tr['trades']}回)",
        f"  検証区間(test)  勝率      : {te['win_rate']*100:.1f}%  "
        f"損益 {te['total_pnl']:+,.0f} 円  ({te['trades']}回)",
        "  ----------------------------------------------------------",
        f"  → 学習で良く見えた勝率は検証で {drop:+.1f} ポイント変化した。",
        "    『過去データに合わせ込んだ高勝率』が未来では崩れる典型例。",
        "    これが “勝率8割が出るまで設定を探す” ことに意味がない理由。",
    ]
    return "\n".join(lines)
