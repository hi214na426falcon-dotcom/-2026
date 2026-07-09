"""時間帯（JST セッション）分析のテスト。"""

import os
import sys
import unittest
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.sessions import (  # noqa: E402
    bucket_by_slot,
    hour_in_windows,
    parse_hour,
    restrict_signals_to_sessions,
    slot_label,
)
from backtest.strategies import UP  # noqa: E402


@dataclass
class FakeTrade:
    time: Optional[str]
    result: str


class TestParseHour(unittest.TestCase):
    def test_jst_offset(self):
        self.assertEqual(parse_hour("2024-01-01T00:00:00", 9), 9)
        self.assertEqual(parse_hour("2024-01-01T15:00:00", 9), 0)  # 15+9=24 -> 0
        self.assertEqual(parse_hour("2024-01-01T11:00:00", 9), 20)

    def test_epoch(self):
        # 1704067200 = 2024-01-01T00:00:00Z -> +9 = 9時
        self.assertEqual(parse_hour("1704067200", 9), 9)

    def test_bad(self):
        self.assertIsNone(parse_hour(None))
        self.assertIsNone(parse_hour("not-a-time"))


class TestWindows(unittest.TestCase):
    def test_simple(self):
        self.assertTrue(hour_in_windows(20, [(17, 24)]))
        self.assertTrue(hour_in_windows(3, [(0, 6)]))
        self.assertFalse(hour_in_windows(10, [(17, 24), (0, 6)]))

    def test_wrap(self):
        self.assertTrue(hour_in_windows(23, [(22, 4)]))
        self.assertTrue(hour_in_windows(2, [(22, 4)]))
        self.assertFalse(hour_in_windows(10, [(22, 4)]))

    def test_slot_label(self):
        self.assertEqual(slot_label((17, 20)), "17:00-20:00")
        self.assertEqual(slot_label((0, 3)), "00:00-03:00")


class TestRestrict(unittest.TestCase):
    def test_filters_outside_sessions(self):
        times = ["2024-01-01T11:00:00", "2024-01-01T02:00:00", "2024-01-01T18:00:00"]
        # JST: 20時(帯内), 11時(帯外), 3時(帯内)
        signals = [UP, UP, UP]
        out = restrict_signals_to_sessions(times, signals, [(17, 24), (0, 6)], 9)
        self.assertEqual(out, [UP, None, UP])


class TestBucket(unittest.TestCase):
    def test_bucket_by_slot(self):
        trades = [
            FakeTrade("2024-01-01T11:00:00", "win"),   # JST20 -> 20-24
            FakeTrade("2024-01-01T11:30:00", "loss"),  # JST20 -> 20-24
            FakeTrade("2024-01-01T16:00:00", "win"),   # JST1  -> 0-3
        ]
        buckets = bucket_by_slot(trades, [(20, 24), (0, 3)], payout=1.90, tz_offset_hours=9)
        self.assertEqual(int(buckets[(20, 24)]["trades"]), 2)
        self.assertAlmostEqual(buckets[(20, 24)]["win_rate"], 0.5)
        self.assertEqual(int(buckets[(0, 3)]["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
