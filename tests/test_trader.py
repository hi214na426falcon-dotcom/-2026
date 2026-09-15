import unittest

from alpaca_clone.core.models import Candle, TradeOutcome
from alpaca_clone.execution.broker import PaperBroker
from alpaca_clone.paper.trader import PaperTrader
from alpaca_clone.strategy.engine import StrategyConfig


def _up_series(n=60):
    out = []
    t = 1_700_000_000
    for i in range(n):
        c = 100.0 + i
        out.append(Candle(t, open=c - 0.5, high=c + 0.5, low=c - 1.0, close=c, volume=1.0))
        t += 60
    return out


class TestPaperTrader(unittest.TestCase):
    def test_settles_and_wins_on_uptrend(self):
        cfg = StrategyConfig(
            name="always-call",
            expiry_bars=1,
            cooldown_bars=0,
            indicators={"sma2": {"type": "sma", "period": 2}},
            call={"logic": "all", "conditions": [{"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": []},
        )
        events = []
        trader = PaperTrader(cfg, broker=PaperBroker(1000.0), stake=10.0,
                             on_event=events.append)
        for c in _up_series(60):
            trader.feed_candle(c)

        st = trader.state()
        self.assertGreater(st["closed_trades"], 0)
        self.assertEqual(st["losses"], 0)          # 上昇で CALL のみ → 負けなし
        self.assertGreater(st["balance"], 1000.0)  # 残高増
        self.assertTrue(any(e["kind"] == "enter" for e in events))
        self.assertTrue(any(e["kind"] == "settle" for e in events))

    def test_single_position_at_a_time(self):
        cfg = StrategyConfig(
            name="always-call",
            expiry_bars=3,        # 満期が先 → その間は建玉保持
            cooldown_bars=0,
            indicators={"sma2": {"type": "sma", "period": 2}},
            call={"logic": "all", "conditions": [{"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": []},
        )
        trader = PaperTrader(cfg, broker=PaperBroker(1000.0), stake=10.0)
        # 建玉保持中に新規が積み上がらないこと(常に <=1)
        max_open = 0
        for c in _up_series(40):
            trader.feed_candle(c)
            max_open = max(max_open, len(trader.pending))
        self.assertLessEqual(max_open, 1)


if __name__ == "__main__":
    unittest.main()
