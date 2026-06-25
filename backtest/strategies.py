"""シグナル生成戦略。

各戦略は ``Series`` を受け取り、各バーの方向シグナル
（``"UP"`` / ``"DOWN"`` / ``None`` のリスト、長さ = len(series)）を返す。

重要な規約（先読みバイアスの防止）:
- バー i のシグナルは終値 close[0..i] までの情報のみで決定する。
- エンジンはバー i のシグナルに対し close[i] でエントリーする想定。
- したがって戦略内で「未来のバー」を参照してはならない。
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional

from .data import Series
from .indicators import bollinger, ema, macd, rsi

UP = "UP"
DOWN = "DOWN"
Signals = List[Optional[str]]


def strat_random(series: Series, seed: int = 0, trade_prob: float = 0.1) -> Signals:
    """ランダム・ベースライン。

    優位性ゼロの基準線。勝率は約 50% になり、ペイアウト < 2.0 の下では必ず
    期待値マイナスになる——「なんとなく」のエントリーが負ける理由を可視化する。
    """
    rng = random.Random(seed)
    out: Signals = []
    for _ in series.bars:
        if rng.random() < trade_prob:
            out.append(UP if rng.random() < 0.5 else DOWN)
        else:
            out.append(None)
    return out


def strat_rsi_reversal(
    series: Series, period: int = 14, oversold: float = 30.0, overbought: float = 70.0
) -> Signals:
    """RSI 逆張り。売られすぎ→UP、買われすぎ→DOWN。"""
    r = rsi(series.closes, period)
    out: Signals = [None] * len(series)
    for i, v in enumerate(r):
        if v is None:
            continue
        if v < oversold:
            out[i] = UP
        elif v > overbought:
            out[i] = DOWN
    return out


def strat_ma_cross(series: Series, fast: int = 10, slow: int = 30) -> Signals:
    """移動平均クロス（順張り）。ゴールデンクロス→UP、デッドクロス→DOWN。"""
    f = ema(series.closes, fast)
    s = ema(series.closes, slow)
    out: Signals = [None] * len(series)
    for i in range(1, len(series)):
        if None in (f[i], s[i], f[i - 1], s[i - 1]):
            continue
        if f[i - 1] <= s[i - 1] and f[i] > s[i]:
            out[i] = UP
        elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
            out[i] = DOWN
    return out


def strat_bollinger_reversion(
    series: Series, period: int = 20, num_std: float = 2.0
) -> Signals:
    """ボリンジャーバンド逆張り。下限割れ→UP、上限超え→DOWN。"""
    mid, up, lo = bollinger(series.closes, period, num_std)
    c = series.closes
    out: Signals = [None] * len(series)
    for i in range(len(series)):
        if up[i] is None or lo[i] is None:
            continue
        if c[i] < lo[i]:
            out[i] = UP
        elif c[i] > up[i]:
            out[i] = DOWN
    return out


def strat_macd(
    series: Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> Signals:
    """MACD ヒストグラムのゼロクロス（順張り）。"""
    _, _, hist = macd(series.closes, fast, slow, signal)
    out: Signals = [None] * len(series)
    for i in range(1, len(series)):
        if hist[i] is None or hist[i - 1] is None:
            continue
        if hist[i - 1] <= 0 and hist[i] > 0:
            out[i] = UP
        elif hist[i - 1] >= 0 and hist[i] < 0:
            out[i] = DOWN
    return out


STRATEGIES: Dict[str, Callable[..., Signals]] = {
    "random": strat_random,
    "rsi": strat_rsi_reversal,
    "ma_cross": strat_ma_cross,
    "bollinger": strat_bollinger_reversion,
    "macd": strat_macd,
}
