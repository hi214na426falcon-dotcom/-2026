import unittest

from alpaca_clone.backtest.engine import Backtester
from alpaca_clone.core.models import Candle, Direction, TradeOutcome
from alpaca_clone.data.feed import SyntheticFeed, cyclical_feed
from alpaca_clone.strategy.engine import StrategyConfig


def _up_series(n=60):
    """右肩上がりの終値。CALL が必ず勝つ状況。"""
    out = []
    t = 1_700_000_000
    for i in range(n):
        c = 100.0 + i
        out.append(Candle(t, open=c - 0.5, high=c + 0.5, low=c - 1.0, close=c, volume=1.0))
        t += 60
    return out


class TestBacktester(unittest.TestCase):
    def test_always_call_wins_on_uptrend(self):
        cfg = StrategyConfig(
            name="always-call",
            expiry_bars=1,
            cooldown_bars=0,
            indicators={"sma2": {"type": "sma", "period": 2}},
            call={"logic": "all", "conditions": [
                {"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": []},
        )
        bt = Backtester(cfg, starting_balance=1000.0, stake=10.0)
        res = bt.run(_up_series(60))
        self.assertGreater(res.n_trades, 0)
        # 上昇トレンドで CALL のみ → 全勝
        self.assertEqual(res.losses, 0)
        self.assertEqual(res.wins, res.n_trades)
        self.assertGreater(res.ending_balance, res.starting_balance)

    def test_summary_keys(self):
        cfg = StrategyConfig(
            name="s",
            indicators={"sma2": {"type": "sma", "period": 2}},
            call={"logic": "all", "conditions": [{"left": "close", "op": ">", "right": 0}]},
            put={"logic": "all", "conditions": []},
        )
        res = Backtester(cfg).run(_up_series(40))
        summ = res.summary()
        for key in ("trades", "wins", "losses", "win_rate", "profit_factor",
                    "expectancy", "net_pnl", "max_drawdown"):
            self.assertIn(key, summ)

    def test_no_signal_no_trades(self):
        cfg = StrategyConfig(
            name="none",
            indicators={},
            call={"logic": "all", "conditions": []},
            put={"logic": "all", "conditions": []},
        )
        res = Backtester(cfg).run(cyclical_feed(n=100))
        self.assertEqual(res.n_trades, 0)
        self.assertEqual(res.ending_balance, res.starting_balance)

    def test_runs_on_synthetic(self):
        cfg = StrategyConfig(
            name="rsi",
            expiry_bars=1,
            indicators={"rsi14": {"type": "rsi", "period": 14},
                        "bb": {"type": "bollinger", "period": 20, "mult": 2.0}},
            call={"logic": "all", "conditions": [
                {"left": "rsi14", "op": "<", "right": 35},
                {"left": "close", "op": "cross_above", "right": "bb.lower"}]},
            put={"logic": "all", "conditions": [
                {"left": "rsi14", "op": ">", "right": 65},
                {"left": "close", "op": "cross_below", "right": "bb.upper"}]},
        )
        candles = SyntheticFeed(n=400, seed=1).candles()
        res = Backtester(cfg).run(candles)
        # 例外を出さずに完走し、結果が整合していること
        self.assertEqual(res.wins + res.losses + res.ties, res.n_trades)


if __name__ == "__main__":
    unittest.main()
