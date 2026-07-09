"""Dukascopy .bi5 パーサの自己テスト（ネット不要）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

import fetch_dukascopy as fd  # noqa: E402


class TestDatafeed(unittest.TestCase):
    def test_self_test_passes(self):
        self.assertEqual(fd.self_test(), 0)

    def test_pair_scale(self):
        self.assertEqual(fd.pair_scale("USDJPY"), 1000)
        self.assertEqual(fd.pair_scale("EURUSD"), 100000)

    def test_empty_safe(self):
        self.assertEqual(fd.decompress_bi5(b""), b"")
        self.assertEqual(fd.parse_ticks(b"", 100000), [])

    def test_month_is_zero_indexed(self):
        from datetime import datetime, timezone
        url = fd.hour_url("EURUSD", datetime(2024, 1, 2, 10, tzinfo=timezone.utc))
        self.assertIn("/2024/00/02/10h_ticks.bi5", url)  # 1月 = 00


if __name__ == "__main__":
    unittest.main()
