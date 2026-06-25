"""バックテストエンジンの決定論的な正しさを検証."""
import numpy as np
import pandas as pd

from binbot.backtest import BacktestConfig, run_backtest
from binbot.strategy import UP, DOWN, NONE


def _df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="1min", tz="UTC")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c}, index=idx)


def test_up_outcomes_exact():
    df = _df([100, 101, 100, 101, 100])
    sig = pd.Series(UP, index=df.index)
    cfg = BacktestConfig(horizon=1, payout=0.8, one_position=False, tie="loss")
    tr = run_backtest(df, sig, cfg)
    assert list(tr["outcome"]) == ["win", "loss", "win", "loss"]
    assert tr["pnl"].sum() == 0.8 - 1 + 0.8 - 1  # = -0.4


def test_down_is_mirror_of_up():
    df = _df([100, 101, 100, 101, 100])
    cfg = BacktestConfig(horizon=1, payout=0.8, one_position=False, tie="loss")
    up = run_backtest(df, pd.Series(UP, index=df.index), cfg)
    dn = run_backtest(df, pd.Series(DOWN, index=df.index), cfg)
    # 同じ値動きで UP と DOWN は勝敗が反転する
    assert list(up["outcome"]) == ["win", "loss", "win", "loss"]
    assert list(dn["outcome"]) == ["loss", "win", "loss", "win"]


def test_tie_handling():
    df = _df([100, 100])
    sig = pd.Series(UP, index=df.index)
    for tie, expect in [("loss", "loss"), ("win", "win"), ("push", "push")]:
        tr = run_backtest(df, sig, BacktestConfig(horizon=1, tie=tie, one_position=False))
        assert tr.iloc[0]["outcome"] == expect


def test_one_position_blocks_overlap():
    df = _df([100, 101, 102, 103, 104, 105])
    sig = pd.Series(UP, index=df.index)
    cfg = BacktestConfig(horizon=2, one_position=True)
    tr = run_backtest(df, sig, cfg)
    # horizon=2 で同時1ポジ → エントリは t0, t2, ... と重ならない
    entry_times = pd.to_datetime(tr["entry_time"])
    gaps = entry_times.diff().dropna() / pd.Timedelta(minutes=1)
    assert (gaps >= 2).all()


def test_no_lookahead_near_end():
    df = _df([100, 101, 102])
    sig = pd.Series(UP, index=df.index)
    # horizon=1 なら最後のバー(t=2)はエントリ不可 (満期が範囲外)
    tr = run_backtest(df, sig, BacktestConfig(horizon=1, one_position=False))
    assert len(tr) == 2
    assert pd.to_datetime(tr["entry_time"]).max() == df.index[1]


def test_none_signals_no_trades():
    df = _df([100, 101, 102, 103])
    tr = run_backtest(df, pd.Series(NONE, index=df.index), BacktestConfig(horizon=1))
    assert len(tr) == 0
