"""gzip 圧縮 CSV の読み込みと 15 秒足集約のテスト。"""
import gzip
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

from agents.pair_stats import find_pair_files
from backtest.data import load_csv
from fetch_dukascopy import ticks_to_minute_bars

CSV_TEXT = (
    "time,open,high,low,close,volume\n"
    "2024-01-01T10:00:00+00:00,150.1,150.2,150.0,150.15,10\n"
    "2024-01-01T10:01:00+00:00,150.15,150.3,150.1,150.25,12\n"
)


class TestGzipCsv(unittest.TestCase):
    def test_load_csv_gz(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "EURJPY.csv.gz")
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(CSV_TEXT)
            s = load_csv(path, name="EURJPY")
            self.assertEqual(len(s), 2)
            self.assertAlmostEqual(s.bars[1].close, 150.25)
            self.assertEqual(s.bars[0].time, "2024-01-01T10:00:00+00:00")

    def test_plain_csv_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "EURJPY.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write(CSV_TEXT)
            self.assertEqual(len(load_csv(path)), 2)

    def test_find_pair_files_gz(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("EURJPY.csv.gz", "USDJPY.csv", "GBPJPY_2024.csv.gz"):
                with open(os.path.join(d, name), "w") as f:
                    f.write("x")
            self.assertEqual(
                [os.path.basename(p) for p in find_pair_files("EURJPY", d)],
                ["EURJPY.csv.gz"])
            self.assertEqual(
                [os.path.basename(p) for p in find_pair_files("USDJPY", d)],
                ["USDJPY.csv"])
            self.assertEqual(
                [os.path.basename(p) for p in find_pair_files("GBPJPY", d)],
                ["GBPJPY_2024.csv.gz"])


class TestFifteenSecondBars(unittest.TestCase):
    def test_bar_seconds_15(self):
        ticks = [(1000, 1.0, 1.0), (14000, 1.1, 1.0),
                 (16000, 1.2, 1.0), (46000, 1.3, 1.0)]
        bars = ticks_to_minute_bars(
            ticks, datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
            bar_seconds=15)
        self.assertEqual(len(bars), 3)
        self.assertTrue(bars[0]["time"].endswith("10:00:00+00:00"))
        self.assertAlmostEqual(bars[0]["open"], 1.0)
        self.assertAlmostEqual(bars[0]["close"], 1.1)
        self.assertTrue(bars[1]["time"].endswith("10:00:15+00:00"))
        self.assertTrue(bars[2]["time"].endswith("10:00:45+00:00"))

    def test_default_is_minute(self):
        ticks = [(1000, 1.0, 1.0), (59000, 1.1, 1.0)]
        bars = ticks_to_minute_bars(
            ticks, datetime(2024, 1, 1, 10, tzinfo=timezone.utc))
        self.assertEqual(len(bars), 1)


if __name__ == "__main__":
    unittest.main()
