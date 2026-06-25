"""正直な成績指標.

勝率だけを見ると騙されます。このモジュールは「勝率 + その不確かさ + 期待値 +
損益分岐勝率」をまとめて出すことで、6割という数字が本当に意味を持つのかを
判定できるようにします。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """勝率の Wilson スコア信頼区間 (デフォルト95%).

    「100回で60勝」と「20回で12勝」はどちらも勝率0.60だが、後者は区間が広く
    全く信用できない。これを数値で突きつけるための関数。
    """
    if n == 0:
        return (float("nan"), float("nan"))
    phat = wins / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def break_even_winrate(payout: float) -> float:
    """ペイアウト率 payout (勝てば +payout, 負ければ -1) の損益分岐勝率 = 1/(1+payout)."""
    return 1.0 / (1.0 + payout)


@dataclass
class Stats:
    n_trades: int          # 判定が出た取引数 (push除く)
    n_push: int            # 引き分け (価格が動かず) 件数
    wins: int
    losses: int
    win_rate: float        # wins / n_trades
    win_rate_ci95: tuple[float, float]
    payout: float
    break_even_winrate: float
    expectancy: float      # 1取引あたり期待損益 (ステーク=1単位)
    edge_vs_breakeven: float  # win_rate - break_even (プラスなら理論上勝てる)
    total_pnl: float       # 累計損益 (ステーク単位)
    profit_factor: float   # 総利益 / 総損失
    max_drawdown: float    # 資産曲線の最大ドローダウン (ステーク単位)
    avg_trades_per_day: Optional[float] = None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["win_rate_ci95"] = list(self.win_rate_ci95)
        return d

    def summary(self) -> str:
        lo, hi = self.win_rate_ci95
        verdict = "○ 理論上プラス" if self.edge_vs_breakeven > 0 else "× 理論上マイナス"
        return (
            f"取引数={self.n_trades} (push={self.n_push})  "
            f"勝率={self.win_rate:.1%} [95%CI {lo:.1%}–{hi:.1%}]\n"
            f"ペイアウト={self.payout:.0%}  損益分岐勝率={self.break_even_winrate:.1%}  "
            f"→ エッジ={self.edge_vs_breakeven:+.1%} {verdict}\n"
            f"期待値/取引={self.expectancy:+.4f}  累計損益={self.total_pnl:+.1f}  "
            f"PF={self.profit_factor:.2f}  最大DD={self.max_drawdown:.1f}"
        )


def compute_stats(trades: pd.DataFrame, payout: float,
                  bars_per_day: Optional[float] = None) -> Stats:
    """trades DataFrame (列: outcome ∈ {win,loss,push}, pnl) から Stats を計算."""
    if len(trades) == 0:
        return Stats(0, 0, 0, 0, float("nan"), (float("nan"), float("nan")),
                     payout, break_even_winrate(payout), float("nan"),
                     float("nan"), 0.0, float("nan"), 0.0)

    outcomes = trades["outcome"]
    wins = int((outcomes == "win").sum())
    losses = int((outcomes == "loss").sum())
    pushes = int((outcomes == "push").sum())
    decided = wins + losses
    win_rate = wins / decided if decided else float("nan")
    ci = wilson_interval(wins, decided)
    be = break_even_winrate(payout)

    pnl = trades["pnl"].to_numpy(dtype=float)
    total_pnl = float(pnl.sum())
    gross_win = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
    expectancy = float(pnl.mean())

    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    max_dd = float((peak - equity).max()) if len(equity) else 0.0

    atpd = None
    if bars_per_day and bars_per_day > 0 and "entry_time" in trades:
        span_days = max(1e-9, (trades["entry_time"].iloc[-1] - trades["entry_time"].iloc[0])
                        / np.timedelta64(1, "D"))
        atpd = len(trades) / span_days

    return Stats(
        n_trades=decided, n_push=pushes, wins=wins, losses=losses,
        win_rate=win_rate, win_rate_ci95=ci, payout=payout,
        break_even_winrate=be, expectancy=expectancy,
        edge_vs_breakeven=(win_rate - be) if decided else float("nan"),
        total_pnl=total_pnl, profit_factor=profit_factor, max_drawdown=max_dd,
        avg_trades_per_day=atpd,
    )
