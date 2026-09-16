import unittest

from alpaca_clone.backtest.engine import Backtester
from alpaca_clone.core.models import Candle, Direction
from alpaca_clone.strategy.alpaca import AlpacaEngine
from alpaca_clone.strategy.engine import StrategyConfig


def _candles(closes):
    out = []
    t = 1_700_000_000
    prev = closes[0]
    for x in closes:
        out.append(Candle(t, open=prev, high=x + 0.05, low=x - 0.05, close=x, volume=1.0))
        prev = x
        t += 60
    return out


def _zigzag(cycles=40, up=3, down=3, upstep=0.6, downstep=0.36, start=100.0, rising=True):
    """各脚を複数本にしたジグザグ(±2フラクタルで山谷が立つ)。

    rising=True なら純増(上昇トレンド)、False なら純減(下降トレンド)。
    """
    closes = []
    price = start
    for _ in range(cycles):
        for _ in range(up):
            price += upstep if rising else -upstep
            closes.append(price)
        for _ in range(down):
            price += -downstep if rising else downstep
            closes.append(price)
    return _candles(closes)


def rising_zigzag():
    return _zigzag(rising=True)


def falling_zigzag():
    return _zigzag(start=300.0, rising=False)


def _cfg(**scoring):
    base_scoring = {"strong_threshold": 4, "weak_threshold": 3, "allow_weak": True,
                    "min_reasons": 2, "require_mtf_alignment": False}
    base_scoring.update(scoring)
    return StrategyConfig.from_dict({
        "name": "alpaca-test",
        "type": "alpaca_scoring",
        "expiry_bars": 1,
        "structure": {"htf_ratio": 5},
        "scoring": base_scoring,
    })


class TestAlpacaEngine(unittest.TestCase):
    def test_decision_schema(self):
        eng = AlpacaEngine(_cfg(), rising_zigzag())
        d = eng.decide(eng.warmup + 10)
        keys = d.to_dict().keys()
        for k in ("signal", "direction", "trend", "trend_strength", "htf_trend",
                  "noise", "net_score", "confidence", "reasons",
                  "invalidation_conditions"):
            self.assertIn(k, keys)
        self.assertIn(d.signal, ("HIGH", "LOW", "SKIP"))

    def test_no_counter_trend_on_clean_uptrend(self):
        eng = AlpacaEngine(_cfg(), rising_zigzag())
        counts = {"CALL": 0, "PUT": 0}
        for i in range(eng.warmup, len(eng.candles)):
            d = eng.decide(i)
            if d.direction is Direction.CALL:
                counts["CALL"] += 1
            elif d.direction is Direction.PUT:
                counts["PUT"] += 1
        # 明確な上昇では逆張り(PUT)を出さない
        self.assertEqual(counts["PUT"], 0)

    def test_no_counter_trend_on_clean_downtrend(self):
        eng = AlpacaEngine(_cfg(), falling_zigzag())
        counts = {"CALL": 0, "PUT": 0}
        for i in range(eng.warmup, len(eng.candles)):
            d = eng.decide(i)
            if d.direction is Direction.CALL:
                counts["CALL"] += 1
            elif d.direction is Direction.PUT:
                counts["PUT"] += 1
        self.assertEqual(counts["CALL"], 0)

    def test_backtest_integration_consistent(self):
        cfg = _cfg()
        res = Backtester(cfg, starting_balance=1000.0, stake=10.0).run(rising_zigzag())
        self.assertEqual(res.wins + res.losses + res.ties, res.n_trades)
        # 判定JSON 用の confidence は 0..100
        eng = AlpacaEngine(cfg, rising_zigzag())
        d = eng.decide(eng.warmup + 5)
        self.assertTrue(0 <= d.confidence <= 100)

    def test_range_market_mostly_skips(self):
        # 純増ゼロのジグザグ(山も谷も水平=レンジ) → 見送り中心
        flat = _zigzag(upstep=0.6, downstep=0.6)   # net 0 → HH/HL 不成立
        cfg = _cfg(allow_weak=False, strong_threshold=7)  # 既定に近い厳しめ
        res = Backtester(cfg).run(flat)
        self.assertLessEqual(res.n_trades, 5)


if __name__ == "__main__":
    unittest.main()
