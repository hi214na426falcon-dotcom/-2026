"""戦略の挙動 + 合成データの性質 + ペーパートレードの整合性.

ここで「平均回帰データでは逆張りが勝ち越し、ランダムでは勝率≒50%」という
正直な対比を、固定シードで決定論的に確認する。
"""
import numpy as np
import pandas as pd

from binbot import data as D
from binbot.backtest import BacktestConfig, backtest_strategy
from binbot.strategy import get_strategy
from binbot.paper_trader import PaperConfig, run_paper
from binbot.broker import LiveBroker


def test_mean_reversion_beats_50_on_ou():
    df = D.make_sample(kind="ou", n=20000, seed=7)
    _, st = backtest_strategy(df, get_strategy("mean_reversion"),
                              BacktestConfig(horizon=5, payout=0.85))
    assert st.n_trades > 50
    # 平均回帰が存在するデータでは逆張りは 50% を明確に上回るはず
    assert st.win_rate > 0.55


def test_random_walk_is_near_50():
    df = D.make_sample(kind="gbm", n=20000, seed=7)
    _, st = backtest_strategy(df, get_strategy("mean_reversion"),
                              BacktestConfig(horizon=5, payout=0.85))
    # ランダムウォークではエッジが無く 50% 近傍 (±8%)
    assert abs(st.win_rate - 0.50) < 0.08


def test_paper_balance_matches_pnl():
    df = D.make_sample(kind="ou", n=8000, seed=3)
    broker, trades, st = run_paper(
        df, get_strategy("mean_reversion"),
        BacktestConfig(horizon=5, payout=0.85),
        PaperConfig(stake=1.0, max_steps=7000), balance=100000.0,
    )
    # 残高の増減 == 取引損益の合計 (会計の整合性)
    assert abs((broker.get_balance() - 100000.0) - st.total_pnl) < 1e-6
    assert len(trades) > 0


def test_live_broker_is_disabled():
    import pytest
    with pytest.raises(NotImplementedError):
        LiveBroker()
