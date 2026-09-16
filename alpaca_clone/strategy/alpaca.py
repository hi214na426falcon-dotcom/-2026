"""アルパカ式スコアリングエンジン(§10/§11 → HIGH/LOW/SKIP)。

構造検出(structure.StructureView)の因果的スナップショットを入力に、
HIGH/LOW それぞれの加点を合計し、しきい値で HIGH(CALL)/LOW(PUT)/見送り(NONE) を決める。
根拠・確信度・撤回条件も出力する(判定JSON §23 準拠)。

RuleEngine と同じ `.warmup` / `.evaluate(index) -> Signal` を実装するので、
Backtester / PaperTrader からそのまま使える。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from ..core.models import Candle, Direction, Signal
from ..structure import StructureView
from ..structure.detectors import DOWN, UP
from .engine import StrategyConfig

# §11 の既定加点(本人公表値ではない設計案)
_DEFAULT_WEIGHTS = {
    "htf_trend": 3,
    "structure_step": 2,     # HIGH:higher_low / LOW:lower_high
    "level_touch": 2,        # HIGH:support / LOW:resistance
    "trendline_bounce": 2,
    "pullback_bounce": 2,
    "mtf_aligned": 2,
    "strong_structure": 2,
}
_MAX_SCORE = sum(_DEFAULT_WEIGHTS.values())  # 13


@dataclass
class AlpacaDecision:
    """1 足の判定結果(判定JSON §23 準拠)。"""

    index: int
    timestamp: int
    signal: str                      # HIGH | LOW | SKIP
    direction: Direction
    trend: str
    trend_strength: int
    htf_trend: str
    noise: str
    high_score: int
    low_score: int
    net_score: int
    confidence: int
    reasons: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    support: Optional[float] = None
    resistance: Optional[float] = None
    baseline: Optional[float] = None
    deviation_atr: float = 0.0
    entry_price: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["direction"] = self.direction.value
        return d


class AlpacaEngine:
    def __init__(self, config: StrategyConfig, candles: Sequence[Candle]):
        self.config = config
        self.candles = list(candles)

        raw = config.raw or {}
        s = raw.get("structure", {})
        self.view = StructureView(
            self.candles,
            left=int(s.get("swing_left", 2)),
            right=int(s.get("swing_right", 2)),
            htf_ratio=int(s.get("htf_ratio", 10)),
            baseline_period=int(s.get("baseline_period", 20)),
            atr_period=int(s.get("atr_period", 14)),
            touch_atr=float(s.get("touch_atr", 0.5)),
            noise_max=float(s.get("noise_max", 0.5)),
            level_tol_atr=float(s.get("level_tol_atr", 0.4)),
            tl_swings=int(s.get("tl_swings", 3)),
        )

        sc = raw.get("scoring", {})
        self.weights = {**_DEFAULT_WEIGHTS, **sc.get("weights", {})}
        self.strong_threshold = int(sc.get("strong_threshold", 7))
        self.weak_threshold = int(sc.get("weak_threshold", 4))
        self.allow_weak = bool(sc.get("allow_weak", False))
        self.min_reasons = int(sc.get("min_reasons", 2))
        self.require_mtf = bool(sc.get("require_mtf_alignment", False))

    @property
    def warmup(self) -> int:
        return self.view.warmup

    # ---- Backtester/PaperTrader 互換 --------------------------------
    def evaluate(self, index: int) -> Signal:
        d = self.decide(index)
        return Signal(
            timestamp=d.timestamp,
            direction=d.direction,
            expiry_bars=self.config.expiry_bars,
            reason="; ".join(d.reasons) if d.reasons else d.signal,
            confidence=d.confidence / 100.0,
        )

    # ---- 判定本体 ---------------------------------------------------
    def decide(self, index: int) -> AlpacaDecision:
        snap = self.view.at(index)
        ts = self.candles[index].timestamp
        w = self.weights

        close_now = self.candles[index].close
        close_prev = self.candles[index - 1].close if index > 0 else close_now
        turned_up = close_now > close_prev
        turned_down = close_now < close_prev

        high_reasons: List[str] = []
        low_reasons: List[str] = []
        high = 0
        low = 0

        # 1) 上位足トレンド
        if snap.htf_trend == UP:
            high += w["htf_trend"]; high_reasons.append("上位足が上昇")
        elif snap.htf_trend == DOWN:
            low += w["htf_trend"]; low_reasons.append("上位足が下降")

        # 2) 構造の切り上げ/切り下げ
        if snap.higher_low:
            high += w["structure_step"]; high_reasons.append("安値切り上げ(HL)")
        if snap.lower_high:
            low += w["structure_step"]; low_reasons.append("高値切り下げ(LH)")

        # 3) サポレジ接触
        if snap.support_touch:
            high += w["level_touch"]; high_reasons.append("サポート接触")
        if snap.resistance_touch:
            low += w["level_touch"]; low_reasons.append("レジスタンス接触")

        # 4) トレンドライン反発/反落
        if snap.tl_bounce_up:
            high += w["trendline_bounce"]; high_reasons.append("上昇TLで反発")
        if snap.tl_bounce_down:
            low += w["trendline_bounce"]; low_reasons.append("下降TLで反落")

        # 5) 短期逆行(ノイズ)後の反発/反落
        if snap.base_trend == UP and snap.noise_state == "pullback" and turned_up:
            high += w["pullback_bounce"]; high_reasons.append("押し目からの反発")
        if snap.base_trend == DOWN and snap.noise_state == "throwback" and turned_down:
            low += w["pullback_bounce"]; low_reasons.append("戻りからの反落")

        # 6) 上位足と下位足の一致
        if snap.base_trend == UP and snap.htf_trend == UP:
            high += w["mtf_aligned"]; high_reasons.append("上位足と短期足が一致(上)")
        if snap.base_trend == DOWN and snap.htf_trend == DOWN:
            low += w["mtf_aligned"]; low_reasons.append("上位足と短期足が一致(下)")

        # 7) 強い構造
        if snap.base_trend == UP and snap.base_strength >= 3:
            high += w["strong_structure"]; high_reasons.append("強い上昇構造")
        if snap.base_trend == DOWN and snap.base_strength >= 3:
            low += w["strong_structure"]; low_reasons.append("強い下降構造")

        net = high - low
        signal, direction, reasons = self._resolve(net, high_reasons, low_reasons, snap)

        max_score = sum(w.values()) or _MAX_SCORE
        confidence = min(100, int(round(abs(net) / max_score * 100)))
        if signal == "SKIP":
            confidence = min(confidence, 40)

        return AlpacaDecision(
            index=index, timestamp=ts, signal=signal, direction=direction,
            trend=snap.base_trend, trend_strength=snap.base_strength,
            htf_trend=snap.htf_trend, noise=snap.noise_state,
            high_score=high, low_score=low, net_score=net, confidence=confidence,
            reasons=reasons,
            invalidation_conditions=self._invalidations(direction, snap),
            support=snap.nearest_support, resistance=snap.nearest_resistance,
            baseline=snap.baseline, deviation_atr=round(snap.deviation_atr, 3),
            entry_price=close_now if direction is not Direction.NONE else None,
        )

    # ---- 判定ロジック(§10/§11) ------------------------------------
    def _resolve(self, net, high_reasons, low_reasons, snap):
        # 上位・短期が完全逆なら見送り(§10)
        if self.require_mtf and snap.base_trend and snap.htf_trend:
            if {snap.base_trend, snap.htf_trend} == {UP, DOWN}:
                return "SKIP", Direction.NONE, ["上位足と短期足が逆方向 → 見送り"]

        if net >= self.strong_threshold and len(high_reasons) >= self.min_reasons:
            return "HIGH", Direction.CALL, high_reasons
        if net <= -self.strong_threshold and len(low_reasons) >= self.min_reasons:
            return "LOW", Direction.PUT, low_reasons
        if self.allow_weak:
            if net >= self.weak_threshold and len(high_reasons) >= self.min_reasons:
                return "HIGH", Direction.CALL, high_reasons + ["(弱シグナル)"]
            if net <= -self.weak_threshold and len(low_reasons) >= self.min_reasons:
                return "LOW", Direction.PUT, low_reasons + ["(弱シグナル)"]

        # 見送り理由
        why = "根拠不足/レンジ" if abs(net) < self.weak_threshold else "弱シグナルのため見送り"
        return "SKIP", Direction.NONE, [why]

    def _invalidations(self, direction: Direction, snap) -> List[str]:
        if direction is Direction.CALL:
            out = ["上位足が下降に転換", "直近安値を明確に割れる(BOS)"]
            if snap.nearest_support is not None:
                out.append(f"サポート {round(snap.nearest_support, 4)} 割れ")
            return out
        if direction is Direction.PUT:
            out = ["上位足が上昇に転換", "直近高値を明確に超える(BOS)"]
            if snap.nearest_resistance is not None:
                out.append(f"レジスタンス {round(snap.nearest_resistance, 4)} 超え")
            return out
        return []
