"""ルールエンジン: 宣言的な設定から売買シグナルを生成する。

「アルパカの考え方」は、文字起こしから抽出した売買ルールをこの JSON 設定に
落とし込むことで表現する。コードを書き換えずに手法を差し替えられる。

設定例(config/strategies/*.json 参照):

    {
      "name": "RSI reversal (example)",
      "timeframe": "M1",
      "expiry_bars": 1,
      "cooldown_bars": 3,
      "indicators": {
        "rsi14": {"type": "rsi", "period": 14},
        "sma50": {"type": "sma", "period": 50},
        "bb":    {"type": "bollinger", "period": 20, "mult": 2.0}
      },
      "filters": [],
      "call": {"logic": "all", "conditions": [
        {"left": "rsi14", "op": "<", "right": 30},
        {"left": "close", "op": "cross_above", "right": "bb.lower"}
      ]},
      "put":  {"logic": "all", "conditions": [
        {"left": "rsi14", "op": ">", "right": 70},
        {"left": "close", "op": "cross_below", "right": "bb.upper"}
      ]}
    }

対応オペレータ: > < >= <= == !=  cross_above cross_below  between  rising falling
被演算子(left/right): 数値, "open/high/low/close/volume", 指標名(例 "rsi14"),
サブ系列(例 "bb.upper", "stoch.k")。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from ..core import indicators as ind
from ..core.models import Candle, Direction, Signal

Number = Union[int, float]
Series = List[Optional[float]]

_OHLCV = ("open", "high", "low", "close", "volume")
_COMPARATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass
class StrategyConfig:
    """パース済みの戦略設定。"""

    name: str
    expiry_bars: int = 1
    timeframe: str = "M1"
    cooldown_bars: int = 0
    payout_rate: float = 0.85
    indicators: Dict[str, dict] = field(default_factory=dict)
    filters: List[dict] = field(default_factory=list)
    call: dict = field(default_factory=lambda: {"logic": "all", "conditions": []})
    put: dict = field(default_factory=lambda: {"logic": "all", "conditions": []})

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyConfig":
        return cls(
            name=d.get("name", "unnamed"),
            expiry_bars=int(d.get("expiry_bars", 1)),
            timeframe=d.get("timeframe", "M1"),
            cooldown_bars=int(d.get("cooldown_bars", 0)),
            payout_rate=float(d.get("payout_rate", 0.85)),
            indicators=d.get("indicators", {}),
            filters=d.get("filters", []),
            call=d.get("call", {"logic": "all", "conditions": []}),
            put=d.get("put", {"logic": "all", "conditions": []}),
        )


def load_strategy(path: Union[str, Path]) -> StrategyConfig:
    """JSON ファイルから戦略設定を読み込む。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return StrategyConfig.from_dict(data)


class RuleEngine:
    """ローソク足に対して指標を計算し、各足でシグナルを判定する。

    使い方:
        engine = RuleEngine(config, candles)
        signal = engine.evaluate(i)   # i 本目(0-based)の確定足に対する判断
    """

    def __init__(self, config: StrategyConfig, candles: Sequence[Candle]):
        self.config = config
        self.candles = list(candles)
        self.series: Dict[str, Series] = {}
        self._build_series()

    # ---- 系列の構築 -------------------------------------------------
    def _build_series(self) -> None:
        opens = [c.open for c in self.candles]
        highs = [c.high for c in self.candles]
        lows = [c.low for c in self.candles]
        closes = [c.close for c in self.candles]
        volumes = [c.volume for c in self.candles]

        self.series["open"] = list(opens)
        self.series["high"] = list(highs)
        self.series["low"] = list(lows)
        self.series["close"] = list(closes)
        self.series["volume"] = list(volumes)

        src_map = {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }

        for name, spec in self.config.indicators.items():
            itype = spec.get("type", "").lower()
            src_name = spec.get("source", "close")
            src = src_map.get(src_name, closes)
            period = int(spec.get("period", 14))

            if itype == "sma":
                self.series[name] = ind.sma(src, period)
            elif itype == "ema":
                self.series[name] = ind.ema(src, period)
            elif itype == "rsi":
                self.series[name] = ind.rsi(src, period)
            elif itype == "momentum":
                self.series[name] = ind.momentum(src, period)
            elif itype == "roc":
                self.series[name] = ind.roc(src, period)
            elif itype == "highest":
                self.series[name] = ind.highest(src, period)
            elif itype == "lowest":
                self.series[name] = ind.lowest(src, period)
            elif itype == "atr":
                self.series[name] = ind.atr(highs, lows, closes, period)
            elif itype == "bollinger":
                mult = float(spec.get("mult", 2.0))
                mid, up, lo = ind.bollinger(src, period, mult)
                self.series[f"{name}.mid"] = mid
                self.series[f"{name}.upper"] = up
                self.series[f"{name}.lower"] = lo
            elif itype == "stochastic":
                k, d = ind.stochastic(
                    highs, lows, closes,
                    int(spec.get("k_period", spec.get("period", 14))),
                    int(spec.get("d_period", 3)),
                )
                self.series[f"{name}.k"] = k
                self.series[f"{name}.d"] = d
            else:
                raise ValueError(f"未知の指標タイプ: {itype!r} (indicator '{name}')")

    @property
    def warmup(self) -> int:
        """信頼できる判定に必要な最小の足数(概算)。"""
        periods = [int(s.get("period", 14)) for s in self.config.indicators.values()]
        periods += [int(s.get("k_period", 0)) for s in self.config.indicators.values()]
        return max(periods, default=1) + 2

    # ---- 判定 -------------------------------------------------------
    def evaluate(self, index: int) -> Signal:
        """index 本目の確定足に対するシグナルを返す。"""
        ts = self.candles[index].timestamp

        if not self._filters_pass(index):
            return Signal(ts, Direction.NONE, self.config.expiry_bars, "filter")

        call_ok = self._block_fires(self.config.call, index)
        put_ok = self._block_fires(self.config.put, index)

        if call_ok and not put_ok:
            return Signal(ts, Direction.CALL, self.config.expiry_bars,
                          self._describe(self.config.call, index))
        if put_ok and not call_ok:
            return Signal(ts, Direction.PUT, self.config.expiry_bars,
                          self._describe(self.config.put, index))
        # 両立 or どちらも不成立 → 見送り
        return Signal(ts, Direction.NONE, self.config.expiry_bars, "no-signal")

    # ---- 内部 -------------------------------------------------------
    def _filters_pass(self, index: int) -> bool:
        """フィルタは空なら常に通過。ある場合は全条件を満たす必要がある。"""
        conds = self.config.filters
        if not conds:
            return True
        return all(self._eval_condition(c, index) for c in conds)

    def _block_fires(self, block: dict, index: int) -> bool:
        """call/put ブロックの発火判定。条件が空なら発火しない。"""
        conds = block.get("conditions", [])
        if not conds:
            return False
        results = [self._eval_condition(c, index) for c in conds]
        if block.get("logic", "all") == "any":
            return any(results)
        return all(results)

    def _eval_condition(self, cond: dict, i: int) -> bool:
        op = cond["op"]
        left = cond["left"]
        right = cond.get("right")

        if op in _COMPARATORS:
            a = self._val(left, i)
            b = self._val(right, i)
            if a is None or b is None:
                return False
            return _COMPARATORS[op](a, b)

        if op in ("cross_above", "cross_below"):
            a0, a1 = self._val(left, i - 1), self._val(left, i)
            b0, b1 = self._val(right, i - 1), self._val(right, i)
            if None in (a0, a1, b0, b1):
                return False
            if op == "cross_above":
                return a0 <= b0 and a1 > b1
            return a0 >= b0 and a1 < b1

        if op == "between":
            if not isinstance(right, (list, tuple)) or len(right) != 2:
                raise ValueError("between の right は [lo, hi] が必要")
            a = self._val(left, i)
            lo = self._val(right[0], i)
            hi = self._val(right[1], i)
            if None in (a, lo, hi):
                return False
            return lo <= a <= hi

        if op in ("rising", "falling"):
            lookback = int(right) if isinstance(right, (int, float)) else 1
            a0, a1 = self._val(left, i - lookback), self._val(left, i)
            if a0 is None or a1 is None:
                return False
            return a1 > a0 if op == "rising" else a1 < a0

        raise ValueError(f"未知のオペレータ: {op!r}")

    def _val(self, operand, i: int) -> Optional[float]:
        """被演算子を index i の数値に解決する。"""
        if i < 0 or i >= len(self.candles):
            return None
        if isinstance(operand, (int, float)):
            return float(operand)
        if isinstance(operand, str):
            s = operand.strip()
            try:
                return float(s)
            except ValueError:
                pass
            if s in self.series:
                return self.series[s][i]
            raise ValueError(f"未知の被演算子: {operand!r} (定義済み系列: {sorted(self.series)})")
        raise ValueError(f"被演算子の型が不正: {operand!r}")

    def _describe(self, block: dict, index: int) -> str:
        conds = block.get("conditions", [])
        parts = [f"{c['left']} {c['op']} {c.get('right')}" for c in conds]
        return f"{block.get('logic', 'all')}[{', '.join(parts)}]"
