import unittest

from alpaca_clone.core import indicators as ind


class TestIndicators(unittest.TestCase):
    def test_sma_basic(self):
        vals = [1, 2, 3, 4, 5]
        out = ind.sma(vals, 3)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], 3.0)
        self.assertAlmostEqual(out[4], 4.0)

    def test_ema_length_and_warmup(self):
        vals = list(range(1, 21))
        out = ind.ema(vals, 5)
        self.assertEqual(len(out), len(vals))
        self.assertIsNone(out[3])
        self.assertIsNotNone(out[4])

    def test_rsi_bounds(self):
        # 単調増加 → RSI は 100 に近づく
        up = list(range(1, 40))
        r = ind.rsi(up, 14)
        self.assertIsNotNone(r[20])
        self.assertGreater(r[20], 99.0)
        # 単調減少 → 0 に近づく
        down = list(range(40, 1, -1))
        r2 = ind.rsi(down, 14)
        self.assertLess(r2[20], 1.0)

    def test_bollinger_order(self):
        vals = [10 + (i % 5) for i in range(50)]
        mid, up, lo = ind.bollinger(vals, 20, 2.0)
        i = 40
        self.assertLess(lo[i], mid[i])
        self.assertLess(mid[i], up[i])

    def test_atr_positive(self):
        highs = [i + 1.5 for i in range(30)]
        lows = [i - 1.5 for i in range(30)]
        closes = [float(i) for i in range(30)]
        a = ind.atr(highs, lows, closes, 14)
        self.assertIsNotNone(a[20])
        self.assertGreater(a[20], 0)

    def test_period_validation(self):
        with self.assertRaises(ValueError):
            ind.sma([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()
