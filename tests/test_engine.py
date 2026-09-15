import unittest

from alpaca_clone.core.models import Candle, Direction
from alpaca_clone.strategy.engine import RuleEngine, StrategyConfig


def _mk(closes):
    """終値列から簡易ローソク足を作る(OHLC を close 近傍で近似)。"""
    out = []
    t = 1_700_000_000
    prev = closes[0]
    for c in closes:
        out.append(Candle(t, open=prev, high=max(prev, c) + 0.1,
                          low=min(prev, c) - 0.1, close=c, volume=1.0))
        prev = c
        t += 60
    return out


class TestRuleEngine(unittest.TestCase):
    def test_threshold_call_put(self):
        cfg = StrategyConfig(
            name="t",
            indicators={"sma3": {"type": "sma", "period": 3}},
            call={"logic": "all", "conditions": [
                {"left": "close", "op": ">", "right": "sma3"}]},
            put={"logic": "all", "conditions": [
                {"left": "close", "op": "<", "right": "sma3"}]},
        )
        candles = _mk([10, 10, 10, 20])  # 最後は sma より大幅に上
        eng = RuleEngine(cfg, candles)
        sig = eng.evaluate(3)
        self.assertEqual(sig.direction, Direction.CALL)

        candles2 = _mk([10, 10, 10, 1])
        eng2 = RuleEngine(cfg, candles2)
        self.assertEqual(eng2.evaluate(3).direction, Direction.PUT)

    def test_cross_above(self):
        cfg = StrategyConfig(
            name="x",
            indicators={"sma2": {"type": "sma", "period": 2}},
            call={"logic": "all", "conditions": [
                {"left": "close", "op": "cross_above", "right": "sma2"}]},
            put={"logic": "all", "conditions": []},
        )
        # close が sma を下から上に抜ける状況を作る
        candles = _mk([10, 9, 8, 12])
        eng = RuleEngine(cfg, candles)
        # index 3 で close(12) が sma2 を上抜け
        self.assertEqual(eng.evaluate(3).direction, Direction.CALL)

    def test_conflict_returns_none(self):
        cfg = StrategyConfig(
            name="c",
            indicators={},
            call={"logic": "all", "conditions": [
                {"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": [
                {"left": "close", "op": ">", "right": 0}]},
        )
        candles = _mk([5, 5, 5, 5])
        eng = RuleEngine(cfg, candles)
        self.assertEqual(eng.evaluate(3).direction, Direction.NONE)

    def test_filter_blocks(self):
        cfg = StrategyConfig(
            name="f",
            indicators={"rsi5": {"type": "rsi", "period": 5}},
            filters=[{"left": "rsi5", "op": ">", "right": 200}],  # 決して満たさない
            call={"logic": "all", "conditions": [
                {"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": []},
        )
        candles = _mk([1, 2, 3, 4, 5, 6, 7, 8])
        eng = RuleEngine(cfg, candles)
        self.assertEqual(eng.evaluate(7).direction, Direction.NONE)

    def test_unknown_operand_raises(self):
        cfg = StrategyConfig(
            name="e",
            indicators={},
            call={"logic": "all", "conditions": [
                {"left": "nope", "op": ">", "right": 1}]},
        )
        candles = _mk([1, 2, 3])
        eng = RuleEngine(cfg, candles)
        with self.assertRaises(ValueError):
            eng.evaluate(2)


if __name__ == "__main__":
    unittest.main()
