import unittest

from alpaca_clone.core.models import Candle
from alpaca_clone.structure.detectors import (
    UP, DOWN, RANGE, Swing, find_swings, trend_from_swings, resample_htf,
    StructureView,
)


def _c(closes):
    out = []
    t = 1_700_000_000
    prev = closes[0]
    for x in closes:
        out.append(Candle(t, open=prev, high=x + 0.05, low=x - 0.05, close=x, volume=1.0))
        prev = x
        t += 60
    return out


class TestStructure(unittest.TestCase):
    def test_find_swings_peak_and_trough(self):
        highs = [1, 2, 3, 2, 1]
        lows = [1, 0, -1, 0, 1]
        hi, lo = find_swings(highs, lows, left=1, right=1)
        self.assertTrue(any(s.idx == 2 for s in hi))   # 山
        self.assertTrue(any(s.idx == 2 for s in lo))   # 谷

    def test_trend_up_down_range(self):
        up_hi = [Swing(1, 10, "high"), Swing(5, 12, "high")]
        up_lo = [Swing(3, 8, "low"), Swing(7, 9, "low")]
        self.assertEqual(trend_from_swings(up_hi, up_lo)[0], UP)

        dn_hi = [Swing(1, 12, "high"), Swing(5, 10, "high")]
        dn_lo = [Swing(3, 9, "low"), Swing(7, 8, "low")]
        self.assertEqual(trend_from_swings(dn_hi, dn_lo)[0], DOWN)

        rg_hi = [Swing(1, 12, "high"), Swing(5, 12, "high")]
        rg_lo = [Swing(3, 8, "low"), Swing(7, 9, "low")]
        # HH でない(=等値) → レンジ扱い
        self.assertEqual(trend_from_swings(rg_hi, rg_lo)[0], RANGE)

    def test_resample_htf(self):
        candles = _c([float(i) for i in range(10)])
        htf = resample_htf(candles, 5)
        self.assertEqual(len(htf), 2)
        self.assertEqual(htf[0].open, candles[0].open)
        self.assertEqual(htf[0].close, candles[4].close)
        self.assertEqual(htf[0].high, max(c.high for c in candles[:5]))
        self.assertEqual(htf[0].low, min(c.low for c in candles[:5]))

    def test_snapshot_causal_uptrend(self):
        # 上昇ジグザグ(各脚3本 → ±2フラクタルで山谷が立つ) → UP を検出
        closes = []
        price = 100.0
        for _ in range(25):            # 25サイクル×6本 = 150本
            for _ in range(3):
                price += 0.6; closes.append(price)
            for _ in range(3):
                price -= 0.36; closes.append(price)   # 純増(上昇)
        view = StructureView(_c(closes), htf_ratio=5)
        snap = view.at(110)
        self.assertEqual(snap.base_trend, UP)
        self.assertTrue(snap.atr > 0)


if __name__ == "__main__":
    unittest.main()
