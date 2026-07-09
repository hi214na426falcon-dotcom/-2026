"""バックテスト中核ロジックの健全性テスト（標準ライブラリ unittest）。

実行:
    python3 -m unittest discover -s tests -v
または:
    python3 -m unittest tests.test_engine -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import Bar, Series, generate_synthetic  # noqa: E402
from backtest.engine import run_backtest  # noqa: E402
from backtest.indicators import ema, rsi, sma  # noqa: E402
from backtest.strategies import DOWN, UP  # noqa: E402


def make_series(closes):
    bars = [Bar(time=str(i), open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]
    return Series(bars, name="test")


class TestIndicators(unittest.TestCase):
    def test_sma_basic(self):
        out = sma([1, 2, 3, 4, 5], 3)
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], 3.0)
        self.assertAlmostEqual(out[4], 4.0)

    def test_ema_length_and_seed(self):
        out = ema([1, 2, 3, 4, 5, 6], 3)
        self.assertEqual(len(out), 6)
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)  # 最初の3つの SMA = 2.0

    def test_rsi_all_up_is_100(self):
        out = rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], 14)
        self.assertAlmostEqual(out[-1], 100.0)

    def test_rsi_range(self):
        vals = [10, 11, 10.5, 12, 11.5, 13, 12, 14, 13.5, 15, 14, 16, 15, 17, 16, 18]
        out = rsi(vals, 14)
        for v in out:
            if v is not None:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)


class TestEngine(unittest.TestCase):
    def test_deterministic_outcomes(self):
        # closes と固定シグナルから勝敗を厳密に検証
        closes = [100, 101, 99, 100, 101, 99]
        series = make_series(closes)
        signals = [UP, None, DOWN, None, UP, None]
        res = run_backtest(
            series,
            signals,
            payout=2.0,
            expiry_bars=1,
            stake=1000,
            start_balance=100000,
            no_overlap=True,
        )
        # i=0 UP: 100->101 勝ち
        # i=2 DOWN: 99->100 (上昇) 負け
        # i=4 UP: 101->99 (下落) 負け
        m = res.metrics()
        self.assertEqual(int(m["trades"]), 3)
        self.assertEqual(int(m["wins"]), 1)
        self.assertEqual(int(m["losses"]), 2)
        self.assertAlmostEqual(m["total_pnl"], 1000 - 1000 - 1000)
        self.assertAlmostEqual(m["end_balance"], 99000)
        self.assertAlmostEqual(m["win_rate"], 1 / 3)

    def test_payout_breakeven(self):
        # ペイアウト2.0・勝率50%なら損益はゼロ（勝ち負け同数）
        closes = [100, 101, 100, 99, 100, 101, 100, 99]
        series = make_series(closes)
        # UP を毎バー（no_overlap で実際には1本おき）
        signals = [UP] * len(closes)
        res = run_backtest(
            series, signals, payout=2.0, expiry_bars=1, stake=1000, no_overlap=True
        )
        m = res.metrics()
        self.assertEqual(int(m["wins"]), int(m["losses"]))
        self.assertAlmostEqual(m["total_pnl"], 0.0)

    def test_tie_policies(self):
        closes = [100, 100, 100]
        series = make_series(closes)
        signals = [UP, None, None]
        for policy, expected_pnl, expected_key in [
            ("loss", -1000, "losses"),
            ("refund", 0, "ties"),
            ("win", 850, "wins"),
        ]:
            res = run_backtest(
                series, signals, payout=1.85, expiry_bars=1, stake=1000,
                tie_policy=policy, no_overlap=True,
            )
            m = res.metrics()
            self.assertAlmostEqual(m["total_pnl"], expected_pnl, msg=policy)
            self.assertEqual(int(m[expected_key]), 1, msg=policy)

    def test_no_lookahead_on_last_bar(self):
        # 最終バーのシグナルは判定足が無いので取引にならない
        closes = [100, 101]
        series = make_series(closes)
        signals = [None, UP]
        res = run_backtest(series, signals, expiry_bars=1, no_overlap=True)
        self.assertEqual(len(res.trades), 0)

    def test_random_strategy_near_breakeven(self):
        # ランダムウォーク + ランダム戦略は ペイアウト1.85 で負け越す傾向（統計的）
        series = generate_synthetic(n=4000, seed=7, process="randomwalk")
        from backtest.strategies import strat_random

        sig = strat_random(series, seed=7, trade_prob=0.3)
        res = run_backtest(series, sig, payout=1.85, expiry_bars=1, no_overlap=True)
        m = res.metrics()
        # 勝率は 50% 近辺（広めの許容）
        self.assertGreater(m["win_rate"], 0.40)
        self.assertLess(m["win_rate"], 0.60)


if __name__ == "__main__":
    unittest.main()
