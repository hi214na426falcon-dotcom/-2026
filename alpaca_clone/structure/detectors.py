"""構造検出器(pure Python・因果的)。

判定時点 index=i では「i までに確定した」情報しか使わない。
スイングは right 本後に確定するため、swing.idx + right <= i のものだけ採用する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from ..core import indicators as ind
from ..core.models import Candle

# トレンド状態
UP = "UP"
DOWN = "DOWN"
RANGE = "RANGE"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Swing:
    idx: int
    price: float
    kind: str  # "high" | "low"


def find_swings(
    highs: Sequence[float], lows: Sequence[float], left: int = 2, right: int = 2
) -> Tuple[List[Swing], List[Swing]]:
    """フラクタル法でスイング高値/安値を検出する。"""
    hi: List[Swing] = []
    lo: List[Swing] = []
    n = len(highs)
    for j in range(left, n - right):
        wnd_h = highs[j - left : j + right + 1]
        if highs[j] == max(wnd_h) and highs[j] > highs[j - 1] and highs[j] >= highs[j + 1]:
            hi.append(Swing(j, highs[j], "high"))
        wnd_l = lows[j - left : j + right + 1]
        if lows[j] == min(wnd_l) and lows[j] < lows[j - 1] and lows[j] <= lows[j + 1]:
            lo.append(Swing(j, lows[j], "low"))
    return hi, lo


def _monotonic_run(values: Sequence[float], increasing: bool) -> int:
    """末尾から見て単調(増/減)が何連続続くか。"""
    run = 0
    for a, b in zip(reversed(values[:-1]), reversed(values[1:])):
        ok = (b > a) if increasing else (b < a)
        if ok:
            run += 1
        else:
            break
    return run


def trend_from_swings(
    swing_highs: List[Swing], swing_lows: List[Swing]
) -> Tuple[str, int]:
    """確定スイングからトレンド状態と強度(0..3)を返す。"""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return UNKNOWN, 0
    h = [s.price for s in swing_highs]
    l = [s.price for s in swing_lows]
    hh = h[-1] > h[-2]
    hl = l[-1] > l[-2]
    lh = h[-1] < h[-2]
    ll = l[-1] < l[-2]

    if hh and hl:
        strength = 1 + min(2, _monotonic_run(h[-4:], True) + _monotonic_run(l[-4:], True) - 1)
        return UP, max(1, strength)
    if lh and ll:
        strength = 1 + min(2, _monotonic_run(h[-4:], False) + _monotonic_run(l[-4:], False) - 1)
        return DOWN, max(1, strength)
    return RANGE, 0


def resample_htf(candles: Sequence[Candle], ratio: int) -> List[Candle]:
    """下位足 ratio 本を1本に集約して上位足を合成する(完成した足のみ)。"""
    out: List[Candle] = []
    n = len(candles)
    for start in range(0, n - ratio + 1, ratio):
        group = candles[start : start + ratio]
        out.append(Candle(
            timestamp=group[0].timestamp,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
        ))
    return out


def _cluster_levels(prices: List[float], tol: float) -> List[float]:
    """近接する水準をまとめて代表値(平均)にする。"""
    if not prices:
        return []
    ordered = sorted(prices)
    clusters: List[List[float]] = [[ordered[0]]]
    for p in ordered[1:]:
        if abs(p - clusters[-1][-1]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [sum(c) / len(c) for c in clusters]


def _regression_at(points: List[Swing], x: int) -> Optional[float]:
    """スイング点(idx,price)への線形回帰を x=index で評価。"""
    if len(points) < 2:
        return None
    xs = [p.idx for p in points]
    ys = [p.price for p in points]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((xi - mx) ** 2 for xi in xs)
    if denom == 0:
        return None
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(xs, ys)) / denom
    intercept = my - slope * mx
    return slope * x + intercept


@dataclass
class StructureSnapshot:
    """ある足 i における構造の要約。"""

    index: int
    atr: float
    base_trend: str
    base_strength: int
    htf_trend: str
    htf_strength: int
    higher_high: bool
    higher_low: bool
    lower_high: bool
    lower_low: bool
    nearest_support: Optional[float]
    nearest_resistance: Optional[float]
    support_touch: bool
    resistance_touch: bool
    tl_bounce_up: bool
    tl_bounce_down: bool
    baseline: Optional[float]
    deviation_atr: float
    noise_state: str  # noise|pullback|throwback|reversal|unknown
    close: float


class StructureView:
    """OHLC 全体から構造を前計算し、各 index の因果的スナップショットを返す。"""

    def __init__(
        self,
        candles: Sequence[Candle],
        left: int = 2,
        right: int = 2,
        htf_ratio: int = 10,
        baseline_period: int = 20,
        atr_period: int = 14,
        touch_atr: float = 0.5,
        noise_max: float = 0.5,
        level_tol_atr: float = 0.4,
        tl_swings: int = 3,
    ):
        self.candles = list(candles)
        self.left = left
        self.right = right
        self.htf_ratio = max(1, htf_ratio)
        self.touch_atr = touch_atr
        self.noise_max = noise_max
        self.level_tol_atr = level_tol_atr
        self.tl_swings = tl_swings

        highs = [c.high for c in self.candles]
        lows = [c.low for c in self.candles]
        closes = [c.close for c in self.candles]

        self._closes = closes
        self._atr = ind.atr(highs, lows, closes, atr_period)
        self._baseline = ind.ema(closes, baseline_period)
        self._sw_hi, self._sw_lo = find_swings(highs, lows, left, right)

        # 上位足
        self._htf = resample_htf(self.candles, self.htf_ratio)
        if len(self._htf) >= (2 * (left + right) + 2):
            hh = [c.high for c in self._htf]
            ll = [c.low for c in self._htf]
            self._htf_hi, self._htf_lo = find_swings(hh, ll, left, right)
        else:
            self._htf_hi, self._htf_lo = [], []

    @property
    def warmup(self) -> int:
        # 上位足で最低限のスイングが確定するまで待つ
        return max(30, self.htf_ratio * (2 * (self.left + self.right) + 2))

    # ---- 因果的スナップショット -------------------------------------
    def at(self, i: int) -> StructureSnapshot:
        atr = self._atr[i] or _fallback_atr(self._closes, i)
        base_hi = [s for s in self._sw_hi if s.idx + self.right <= i]
        base_lo = [s for s in self._sw_lo if s.idx + self.right <= i]
        base_trend, base_strength = trend_from_swings(base_hi, base_lo)

        # 上位足(完成した足のみ)
        htf_complete = (i + 1) // self.htf_ratio
        htf_limit = htf_complete - 1
        htf_hi = [s for s in self._htf_hi if s.idx + self.right <= htf_limit]
        htf_lo = [s for s in self._htf_lo if s.idx + self.right <= htf_limit]
        htf_trend, htf_strength = trend_from_swings(htf_hi, htf_lo)

        hh = len(base_hi) >= 2 and base_hi[-1].price > base_hi[-2].price
        lh = len(base_hi) >= 2 and base_hi[-1].price < base_hi[-2].price
        hl = len(base_lo) >= 2 and base_lo[-1].price > base_lo[-2].price
        ll = len(base_lo) >= 2 and base_lo[-1].price < base_lo[-2].price

        close = self._closes[i]
        tol = self.level_tol_atr * atr

        supports = _cluster_levels([s.price for s in base_lo[-6:]], tol)
        resistances = _cluster_levels([s.price for s in base_hi[-6:]], tol)
        nearest_sup = _nearest(supports, close)
        nearest_res = _nearest(resistances, close)
        support_touch = nearest_sup is not None and abs(close - nearest_sup) <= self.touch_atr * atr
        resistance_touch = nearest_res is not None and abs(close - nearest_res) <= self.touch_atr * atr

        # トレンドライン反発
        tl_bounce_up = self._tl_bounce(base_lo, i, up=True, atr=atr)
        tl_bounce_down = self._tl_bounce(base_hi, i, up=False, atr=atr)

        baseline = self._baseline[i]
        deviation_atr = ((close - baseline) / atr) if (baseline is not None and atr) else 0.0

        noise_state = self._noise_state(base_trend, base_hi, base_lo, i)

        return StructureSnapshot(
            index=i, atr=atr, base_trend=base_trend, base_strength=base_strength,
            htf_trend=htf_trend, htf_strength=htf_strength,
            higher_high=hh, higher_low=hl, lower_high=lh, lower_low=ll,
            nearest_support=nearest_sup, nearest_resistance=nearest_res,
            support_touch=support_touch, resistance_touch=resistance_touch,
            tl_bounce_up=tl_bounce_up, tl_bounce_down=tl_bounce_down,
            baseline=baseline, deviation_atr=deviation_atr,
            noise_state=noise_state, close=close,
        )

    # ---- 内部 -------------------------------------------------------
    def _tl_bounce(self, swings: List[Swing], i: int, up: bool, atr: float) -> bool:
        pts = swings[-self.tl_swings:]
        if len(pts) < 2 or atr <= 0:
            return False
        line_prev = _regression_at(pts, i - 1)
        if line_prev is None:
            return False
        c_prev, c_now = self._closes[i - 1], self._closes[i]
        near = abs(c_prev - line_prev) <= self.touch_atr * atr
        if up:
            return near and c_now > c_prev  # ライン付近から上へ反発
        return near and c_now < c_prev      # ライン付近から下へ反落

    def _noise_state(self, trend: str, base_hi: List[Swing],
                     base_lo: List[Swing], i: int) -> str:
        close = self._closes[i]
        if trend == UP and base_hi and base_lo:
            peak = base_hi[-1].price
            trough = base_lo[-1].price
            leg = peak - trough
            if leg <= 0:
                return UNKNOWN.lower()
            if close < trough:
                return "reversal"  # Break of Structure(安値割れ)
            retrace = (peak - close) / leg
            return "pullback" if retrace <= self.noise_max else "reversal"
        if trend == DOWN and base_hi and base_lo:
            peak = base_hi[-1].price
            trough = base_lo[-1].price
            leg = peak - trough
            if leg <= 0:
                return UNKNOWN.lower()
            if close > peak:
                return "reversal"  # 高値超え
            retrace = (close - trough) / leg
            return "throwback" if retrace <= self.noise_max else "reversal"
        return "noise" if trend in (UP, DOWN) else UNKNOWN.lower()


def _nearest(levels: List[float], price: float) -> Optional[float]:
    if not levels:
        return None
    return min(levels, key=lambda x: abs(x - price))


def _fallback_atr(closes: Sequence[float], i: int) -> float:
    """ATR 未確定時の簡易代替(直近変動)。0 除算回避用。"""
    if i <= 0:
        return max(1e-9, abs(closes[i]) * 0.001)
    window = closes[max(0, i - 5): i + 1]
    diffs = [abs(b - a) for a, b in zip(window[:-1], window[1:])]
    val = sum(diffs) / len(diffs) if diffs else abs(closes[i]) * 0.001
    return max(1e-9, val)
