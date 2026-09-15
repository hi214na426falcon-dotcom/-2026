"""テクニカル指標(pure Python)。

すべて「入力と同じ長さのリスト」を返す。ウォームアップ期間中は None。
これにより、エンジンは任意の足 index i で `series[i]` を引ける。
外部依存なし(pandas 不要)なのでどこでも動く。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Series = List[Optional[float]]


def sma(values: Sequence[float], period: int) -> Series:
    """単純移動平均。"""
    _check_period(period)
    out: Series = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Sequence[float], period: int) -> Series:
    """指数移動平均。最初の値は SMA でシード。"""
    _check_period(period)
    out: Series = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Sequence[float], period: int = 14) -> Series:
    """RSI(Wilder 平滑)。0..100。"""
    _check_period(period)
    n = len(values)
    out: Series = [None] * n
    if n <= period:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        change = values[i] - values[i - 1]
        gain = change if change > 0 else 0.0
        loss = -change if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def bollinger(
    values: Sequence[float], period: int = 20, mult: float = 2.0
) -> Tuple[Series, Series, Series]:
    """ボリンジャーバンド (mid, upper, lower)。"""
    _check_period(period)
    mid = sma(values, period)
    upper: Series = [None] * len(values)
    lower: Series = [None] * len(values)
    for i in range(len(values)):
        if mid[i] is None:
            continue
        window = values[i - period + 1 : i + 1]
        mean = mid[i]
        var = sum((x - mean) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i] = mean + mult * sd
        lower[i] = mean - mult * sd
    return mid, upper, lower


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> Series:
    """Average True Range(Wilder 平滑)。"""
    _check_period(period)
    n = len(closes)
    out: Series = [None] * n
    if n <= period:
        return out
    trs: List[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    first = sum(trs[1 : period + 1]) / period
    out[period] = first
    prev = first
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def momentum(values: Sequence[float], period: int = 10) -> Series:
    """モメンタム: value[i] - value[i-period]。"""
    _check_period(period)
    out: Series = [None] * len(values)
    for i in range(period, len(values)):
        out[i] = values[i] - values[i - period]
    return out


def roc(values: Sequence[float], period: int = 10) -> Series:
    """変化率(%)。"""
    _check_period(period)
    out: Series = [None] * len(values)
    for i in range(period, len(values)):
        base = values[i - period]
        if base != 0:
            out[i] = (values[i] - base) / base * 100.0
    return out


def highest(values: Sequence[float], period: int) -> Series:
    """直近 period 本の最高値。"""
    _check_period(period)
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = max(values[i - period + 1 : i + 1])
    return out


def lowest(values: Sequence[float], period: int) -> Series:
    """直近 period 本の最安値。"""
    _check_period(period)
    out: Series = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = min(values[i - period + 1 : i + 1])
    return out


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    k_period: int = 14,
    d_period: int = 3,
) -> Tuple[Series, Series]:
    """ストキャスティクス %K, %D。"""
    _check_period(k_period)
    hh = highest(highs, k_period)
    ll = lowest(lows, k_period)
    k: Series = [None] * len(closes)
    for i in range(len(closes)):
        if hh[i] is None or ll[i] is None:
            continue
        rng = hh[i] - ll[i]
        k[i] = 50.0 if rng == 0 else (closes[i] - ll[i]) / rng * 100.0
    # %D は %K の SMA。None を除いて計算するため、詰めて移動平均する。
    d: Series = [None] * len(closes)
    buf: List[float] = []
    for i in range(len(closes)):
        if k[i] is None:
            continue
        buf.append(k[i])
        if len(buf) >= d_period:
            d[i] = sum(buf[-d_period:]) / d_period
    return k, d


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError(f"period は 1 以上が必要: {period}")
