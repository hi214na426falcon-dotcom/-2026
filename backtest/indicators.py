"""テクニカル指標（標準ライブラリのみ）。

設計方針:
- すべての関数は入力 ``values``（float のリスト）と同じ長さのリストを返す。
- 計算に必要なデータが揃わない先頭部分は ``None`` で埋める。
- 指標は「そのバーまでの終値だけ」で計算でき、先読み（未来の値の参照）をしない。
  これによりバックテストの先読みバイアスを構造的に防ぐ。
"""

from __future__ import annotations

from typing import List, Optional, Tuple


def sma(values: List[float], period: int) -> List[Optional[float]]:
    """単純移動平均。"""
    if period <= 0:
        raise ValueError("period must be positive")
    out: List[Optional[float]] = [None] * len(values)
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """指数移動平均。最初の ``period`` 本の SMA を初期値(シード)とする。"""
    if period <= 0:
        raise ValueError("period must be positive")
    out: List[Optional[float]] = [None] * len(values)
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


def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    """RSI（Wilder 方式の平滑化）。0–100。"""
    if period <= 0:
        raise ValueError("period must be positive")
    out: List[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return out

    def rsi_val(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = rsi_val(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = rsi_val(avg_gain, avg_loss)
    return out


def macd(
    values: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """MACD。戻り値は (macd_line, signal_line, histogram)。"""
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    n = len(values)
    macd_line: List[Optional[float]] = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    signal_line: List[Optional[float]] = [None] * n
    hist: List[Optional[float]] = [None] * n

    start = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if start is not None:
        sub = [v for v in macd_line[start:]]  # この区間は None を含まない
        sub_sig = ema(sub, signal)
        for j, val in enumerate(sub_sig):
            signal_line[start + j] = val
        for i in range(n):
            if macd_line[i] is not None and signal_line[i] is not None:
                hist[i] = macd_line[i] - signal_line[i]
    return macd_line, signal_line, hist


def _stdev_pop(window: List[float]) -> float:
    """母標準偏差（ボリンジャーバンドで一般的に使われる定義）。"""
    n = len(window)
    m = sum(window) / n
    return (sum((x - m) ** 2 for x in window) / n) ** 0.5


def bollinger(
    values: List[float],
    period: int = 20,
    num_std: float = 2.0,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """ボリンジャーバンド。戻り値は (middle, upper, lower)。"""
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(values)
    mid = sma(values, period)
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    for i in range(n):
        if i >= period - 1:
            window = values[i - period + 1 : i + 1]
            sd = _stdev_pop(window)
            upper[i] = mid[i] + num_std * sd
            lower[i] = mid[i] - num_std * sd
    return mid, upper, lower
