"""バイナリーオプションのバックテストエンジン (higher/lower 判定).

モデル:
  * 時刻 t で signal != NONE のとき close[t] でエントリ。
  * horizon バー後 (t+horizon) の close で判定:
      UP   勝ち条件: close[t+h] > close[t]
      DOWN 勝ち条件: close[t+h] < close[t]
  * 損益 (ステーク=1):  勝ち → +payout,  負け → -1,  引き分け → tie 設定に従う
  * one_position=True のとき、ポジション保有中の新規シグナルは見送る (重複を防ぐ)。

正直さのための既定値:
  * tie="loss"  … 値動きゼロ(同値)は「負け」扱い。勝率を水増ししない保守側。
  * payout=0.85 … 海外短期バイナリの代表値。国内はペイアウト構造が異なるので
                  実値を --payout で必ず上書きしてください。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .strategy import Strategy, UP, DOWN, NONE
from . import metrics as M


@dataclass
class BacktestConfig:
    horizon: int = 5            # 満期までのバー数
    payout: float = 0.85        # 勝った時の倍率 (+payout)
    one_position: bool = True   # 同時1ポジションのみ
    tie: Literal["loss", "push", "win"] = "loss"
    stake: float = 1.0


def run_backtest(df: pd.DataFrame, signals: pd.Series,
                 cfg: BacktestConfig | None = None) -> pd.DataFrame:
    """シグナルから取引リスト(DataFrame)を生成して返す."""
    cfg = cfg or BacktestConfig()
    close = df["close"].to_numpy(dtype=float)
    times = df.index.to_numpy()
    sig = signals.reindex(df.index).fillna(NONE).to_numpy(dtype=int)
    n = len(df)
    h = cfg.horizon

    rows = []
    open_until = -1
    for t in range(n - h):
        d = sig[t]
        if d == NONE:
            continue
        if cfg.one_position and t <= open_until:
            continue
        entry = close[t]
        exit_i = t + h
        exit_p = close[exit_i]
        diff = exit_p - entry

        if diff == 0.0:
            outcome = {"loss": "loss", "push": "push", "win": "win"}[cfg.tie]
        elif (diff > 0 and d == UP) or (diff < 0 and d == DOWN):
            outcome = "win"
        else:
            outcome = "loss"

        if outcome == "win":
            pnl = cfg.stake * cfg.payout
        elif outcome == "loss":
            pnl = -cfg.stake
        else:
            pnl = 0.0

        rows.append({
            "entry_time": times[t],
            "exit_time": times[exit_i],
            "direction": "UP" if d == UP else "DOWN",
            "entry_price": entry,
            "exit_price": exit_p,
            "outcome": outcome,
            "pnl": pnl,
        })
        open_until = exit_i

    cols = ["entry_time", "exit_time", "direction", "entry_price",
            "exit_price", "outcome", "pnl"]
    return pd.DataFrame(rows, columns=cols)


def estimate_bars_per_day(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return float("nan")
    span_days = (df.index[-1] - df.index[0]) / np.timedelta64(1, "D")
    return len(df) / span_days if span_days > 0 else float("nan")


def backtest_strategy(df: pd.DataFrame, strategy: Strategy,
                      cfg: BacktestConfig | None = None):
    """戦略を当ててバックテストし、(trades, Stats) を返す."""
    cfg = cfg or BacktestConfig()
    signals = strategy.generate(df)
    trades = run_backtest(df, signals, cfg)
    stats = M.compute_stats(trades, payout=cfg.payout,
                            bars_per_day=estimate_bars_per_day(df))
    return trades, stats
