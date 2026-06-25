"""ウォークフォワード検証 (アウトオブサンプル).

なぜ必要か:
  パラメータを全期間で最適化して勝率6割を出すのは簡単 = オーバーフィット。
  それは「過去にピッタリ合う形を後出しで選んだ」だけで、将来の保証にならない。

ここでやること:
  1. データを [学習窓 train] → [検証窓 test] の連続ブロックに分ける。
  2. train だけでパラメータを最適化 (グリッド探索)。
  3. 選んだパラメータを *次の未知の* test 窓に適用 (= アウトオブサンプル)。
  4. 全 test 窓の取引を連結して、正直な勝率/期待値を出す。

この OOS 勝率が、実運用で期待できる現実的な数字に最も近い。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional, Type

import pandas as pd

from .backtest import BacktestConfig, backtest_strategy, run_backtest, estimate_bars_per_day
from .strategy import Strategy
from . import metrics as M


@dataclass
class WFConfig:
    train_bars: int = 6000
    test_bars: int = 2000
    min_trades: int = 25       # train でこれ未満の候補は採用しない
    objective: str = "expectancy"  # "expectancy" or "edge"


def _expand_grid(grid: Dict[str, list]) -> List[dict]:
    if not grid:
        return [dict()]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def _score(stats: M.Stats, objective: str) -> float:
    if stats.n_trades == 0:
        return float("-inf")
    if objective == "edge":
        return stats.edge_vs_breakeven
    return stats.expectancy


def walk_forward(df: pd.DataFrame, strategy_cls: Type[Strategy],
                 bt_cfg: BacktestConfig | None = None,
                 wf_cfg: WFConfig | None = None,
                 grid: Optional[Dict[str, list]] = None):
    """戻り値: (oos_trades, oos_stats, selections[list of dict])."""
    bt_cfg = bt_cfg or BacktestConfig()
    wf_cfg = wf_cfg or WFConfig()
    grid = grid if grid is not None else strategy_cls.param_grid()
    combos = _expand_grid(grid)

    n = len(df)
    oos_parts: List[pd.DataFrame] = []
    selections: List[dict] = []

    start = 0
    while start + wf_cfg.train_bars + wf_cfg.test_bars <= n:
        train = df.iloc[start: start + wf_cfg.train_bars]
        test = df.iloc[start + wf_cfg.train_bars: start + wf_cfg.train_bars + wf_cfg.test_bars]

        best_params, best_score = None, float("-inf")
        for params in combos:
            strat = strategy_cls(params=params)
            _, st = backtest_strategy(train, strat, bt_cfg)
            if st.n_trades < wf_cfg.min_trades:
                continue
            sc = _score(st, wf_cfg.objective)
            if sc > best_score:
                best_score, best_params = sc, params

        if best_params is None:
            # train で十分なトレードが出なければデフォルトで様子見
            best_params = {}

        strat = strategy_cls(params=best_params)
        test_trades = run_backtest(test, strat.generate(test), bt_cfg)
        oos_parts.append(test_trades)
        selections.append({
            "train_start": str(train.index[0]), "test_start": str(test.index[0]),
            "test_end": str(test.index[-1]), "params": best_params,
            "train_score": best_score, "oos_trades": len(test_trades),
        })
        start += wf_cfg.test_bars  # 非重複の検証窓を前進

    oos_trades = (pd.concat(oos_parts, ignore_index=True)
                  if oos_parts else pd.DataFrame(
                      columns=["entry_time", "exit_time", "direction",
                               "entry_price", "exit_price", "outcome", "pnl"]))
    oos_stats = M.compute_stats(oos_trades, payout=bt_cfg.payout,
                                bars_per_day=estimate_bars_per_day(df))
    return oos_trades, oos_stats, selections
