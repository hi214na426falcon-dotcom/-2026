"""指標の基本性質を検証 (look-ahead 無しでの妥当性)."""
import numpy as np
import pandas as pd

from binbot import indicators as ind


def _series(vals):
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="1min", tz="UTC")
    return pd.Series(np.array(vals, dtype=float), index=idx)


def test_rsi_bounds_and_extremes():
    up = _series(np.arange(1, 200, dtype=float))   # 単調増加
    r = ind.rsi(up, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
    assert r.iloc[-1] > 95   # ずっと上昇なら RSI は高い

    dn = _series(np.arange(200, 1, -1, dtype=float))
    r2 = ind.rsi(dn, 14).dropna()
    assert r2.iloc[-1] < 5   # ずっと下落なら RSI は低い


def test_bollinger_ordering():
    s = _series(np.random.default_rng(0).normal(100, 1, 300))
    mid, up, lo = ind.bollinger(s, 20, 2.0)
    valid = mid.dropna().index
    assert (up.loc[valid] >= mid.loc[valid]).all()
    assert (mid.loc[valid] >= lo.loc[valid]).all()


def test_zscore_zero_mean_ish():
    s = _series(np.random.default_rng(1).normal(0, 1, 1000))
    z = ind.zscore(s, 50).dropna()
    assert abs(z.mean()) < 0.5   # おおむね中心0


def test_atr_positive():
    n = 200
    rng = np.random.default_rng(2)
    c = 100 + np.cumsum(rng.normal(0, 0.1, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1, "close": c}, index=idx)
    a = ind.atr(df, 14).dropna()
    assert (a > 0).all()
