"""fetch_history.py のユニットテスト（通信なし）.

実行: python3 -I -m unittest discover -s automation/tests -v
"""
from __future__ import annotations

import calendar
import contextlib
import glob
import io
import lzma
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_history as fh  # noqa: E402

SERVER = "HFMarketsSV-Demo Server 2"


def ts(s: str) -> int:
    """'YYYY-MM-DD HH:MM' を UTC とみなしたエポック秒."""
    return calendar.timegm(datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())


def bi5(records: list[tuple]) -> bytes:
    """(秒, 始, 終, 安, 高, 出来高) のリストから Dukascopy 形式の bi5 を作る."""
    return lzma.compress(b"".join(fh.BI5_REC.pack(*r) for r in records), format=lzma.FORMAT_ALONE)


def minutes(hhmm: str, n: int, price: int = 2_000_000) -> list[tuple]:
    """hhmm（UTC）から n 本の連続した1分足（価格は1分ごとに 0.01 ずつ上がる）."""
    h, m = map(int, hhmm.split(":"))
    return [((h * 60 + m + i) * 60, price + 10 * i, price + 10 * i + 5, price + 10 * i - 20,
             price + 10 * i + 30, 2.4) for i in range(n)]


def bar(ctm: int, price: float = 2000.0, vol: int = 4) -> fh.Bar:
    return fh.Bar(ctm, price, price + 1, price - 1, price + 0.5, vol)


def store_of(bars: list[fh.Bar]) -> fh.BarStore:
    s = fh.BarStore()
    s.add(bars)
    return s


class TestDaysAndUrl(unittest.TestCase):
    def test_url_month_is_zero_based(self):
        self.assertEqual(fh.day_url("XAUUSD", date(2026, 1, 5)),
                         "https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/00/05/BID_candles_min_1.bi5")
        self.assertIn("/2025/11/31/", fh.day_url("XAUUSD", date(2025, 12, 31)))

    def test_saturdays_are_skipped(self):
        days = fh.trading_days(date(2026, 3, 26), date(2026, 3, 30))
        self.assertEqual(days, [date(2026, 3, 26), date(2026, 3, 27), date(2026, 3, 29), date(2026, 3, 30)])
        self.assertEqual(fh.trading_days(date(2026, 3, 28), date(2026, 3, 28)), [])

    def test_parse_date(self):
        self.assertEqual(fh.parse_date("2021.10.01"), date(2021, 10, 1))
        with self.assertRaises(Exception):
            fh.parse_date("2021-13-01")


class TestServerTime(unittest.TestCase):
    def test_summer_and_winter(self):
        self.assertEqual(fh.to_server_time(ts("2026-07-01 10:00")), ts("2026-07-01 13:00"))
        self.assertEqual(fh.to_server_time(ts("2026-12-01 10:00")), ts("2026-12-01 12:00"))
        self.assertEqual(fh.to_server_time(ts("2026-01-15 23:30")), ts("2026-01-16 01:30"))

    def test_last_sundays(self):
        self.assertEqual(fh.last_sunday(2026, 3), date(2026, 3, 29))
        self.assertEqual(fh.last_sunday(2026, 10), date(2026, 10, 25))
        self.assertEqual(fh.last_sunday(2024, 3), date(2024, 3, 31))  # 31日が日曜

    def test_dst_start_boundary(self):
        self.assertEqual(fh.server_offset(ts("2026-03-29 00:59")), 2 * 3600)
        self.assertEqual(fh.server_offset(ts("2026-03-29 01:00")), 3 * 3600)
        self.assertEqual(fh.to_server_time(ts("2026-03-29 01:00")), ts("2026-03-29 04:00"))

    def test_dst_end_boundary(self):
        self.assertEqual(fh.server_offset(ts("2026-10-25 00:59")), 3 * 3600)
        self.assertEqual(fh.server_offset(ts("2026-10-25 01:00")), 2 * 3600)
        self.assertEqual(fh.to_server_time(ts("2026-10-25 01:00")), ts("2026-10-25 03:00"))


class TestBi5(unittest.TestCase):
    def test_field_order_open_close_low_high(self):
        raw = fh.decompress_bi5(bi5([(600, 2_000_500, 2_001_000, 1_999_000, 2_002_000, 1.5)]))
        recs = fh.parse_bi5(raw)
        self.assertEqual(recs[0][:5], (600, 2_000_500, 2_001_000, 1_999_000, 2_002_000))
        b = fh.day_bars(date(2026, 7, 1), recs, 1000, 2)[0]
        self.assertEqual((b.open, b.high, b.low, b.close), (2000.5, 2002.0, 1999.0, 2001.0))
        self.assertEqual(b.ctm, ts("2026-07-01 03:10"))  # 00:10 UTC + 3h

    def test_divisor_auto_detect(self):
        self.assertEqual(fh.detect_divisor([2_000_000, 2_001_000, 1_999_000]), 1000)
        self.assertEqual(fh.detect_divisor([150_000]), 100)
        self.assertEqual(fh.detect_divisor([300_000_000]), 100000)
        self.assertEqual(fh.detect_divisor([15_000]), 10)
        with self.assertRaises(ValueError):
            fh.detect_divisor([50])

    def test_filler_and_bad_records_dropped(self):
        recs = [(0, 2_000_000, 2_000_000, 2_000_000, 2_000_000, 0.0),  # 出来高0・値動きなし → 捨てる
                (60, 2_000_000, 2_000_100, 1_999_900, 2_000_200, 0.0),  # 出来高0でも値動きあり → 残す
                (120, 0, 2_000_000, 2_000_000, 2_000_000, 1.0),  # 価格0 → 捨てる
                (180, 2_000_000, 2_000_000, 2_000_000, 2_000_000, float("nan"))]  # NaN出来高・値動きなし → 捨てる
        bars = fh.day_bars(date(2026, 12, 1), recs, 1000, 2, min_volume=4)
        self.assertEqual([b.ctm for b in bars], [ts("2026-12-01 02:01")])
        self.assertEqual(bars[0].volume, 4)

    def test_minute_alignment_dedupe_rounding_volume(self):
        recs = [(600, 2_000_123, 2_000_000, 1_999_000, 2_001_000, 1.0),
                (630, 2_100_000, 2_100_000, 2_099_000, 2_101_000, 7.6)]  # 同じ分 → 後勝ち
        bars = fh.day_bars(date(2026, 12, 1), recs, 1000, 2, min_volume=1)
        self.assertEqual(len(bars), 1)
        self.assertEqual((bars[0].ctm, bars[0].open, bars[0].volume), (ts("2026-12-01 02:10"), 2100.0, 8))
        rounded = fh.day_bars(date(2026, 12, 1), recs[:1], 1000, 2)[0]
        self.assertEqual(rounded.open, 2000.12)

    def test_high_low_cover_open_close(self):
        b = fh.day_bars(date(2026, 12, 1), [(0, 2_000_000, 2_005_000, 2_001_000, 2_003_000, 1.0)], 1000)[0]
        self.assertEqual((b.high, b.low), (2005.0, 2000.0))

    def test_empty_and_corrupt(self):
        self.assertEqual(fh.decompress_bi5(b""), b"")
        with self.assertRaises(ValueError):
            fh.decompress_bi5(b"<html>not found</html>")


class TestHst(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "XAUUSD1.hst")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sizes_and_round_trip(self):
        self.assertEqual(fh.HST_HEADER.size, 148)
        self.assertEqual(fh.HST_REC.size, 60)
        bars = [bar(ts("2026-01-05 01:00") + 60 * i, 2000 + i, 5 + i) for i in range(3)]
        fh.write_hst(self.path, "XAUUSD", 2, store_of(bars))
        self.assertEqual(os.path.getsize(self.path), 148 + 60 * 3)
        header, got = fh.read_hst(self.path)
        self.assertEqual(header, {"version": 401, "copyright": fh.COPYRIGHT.decode(), "symbol": "XAUUSD",
                                  "period": 1, "digits": 2})
        self.assertEqual(got, bars)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_read_version_400(self):
        with open(self.path, "wb") as f:
            f.write(fh.HST_HEADER.pack(400, fh.COPYRIGHT, b"XAUUSD", 1, 2, 0, 0))
            f.write(fh.HST400_REC.pack(1000, 1.0, 0.5, 2.0, 1.5, 7.0))  # 時刻, 始, 安, 高, 終, 出来高
        self.assertEqual(fh.read_hst(self.path)[1], [fh.Bar(1000, 1.0, 2.0, 0.5, 1.5, 7)])

    def test_store_overlap_keeps_sorted_unique_later_wins(self):
        s = store_of([bar(60), bar(120), bar(180)])
        s.add([bar(120, 3000), bar(150, 3000)])
        self.assertEqual([(b.ctm, b.open) for b in s.bars()],
                         [(60, 2000), (120, 3000), (150, 3000), (180, 2000)])
        s.add([bar(0), bar(60, 4000)])  # 先頭より前と重なっても並べ直す
        self.assertEqual(list(s.ctm), [0, 60, 120, 150, 180])
        self.assertEqual(list(s.bars())[1].open, 4000)

    def test_merge_keeps_only_newer_existing_bars(self):
        t = ts("2026-03-30 10:00")
        fh.write_hst(self.path, "XAUUSD", 2, store_of([bar(t - 600, 1), bar(t, 1), bar(t + 60, 1), bar(t + 120, 1)]))
        s = store_of([bar(t - 60), bar(t)])
        self.assertEqual(fh.merge_existing(s, self.path), 2)
        self.assertEqual([(b.ctm, b.open) for b in s.bars()],
                         [(t - 60, 2000), (t, 2000), (t + 60, 1), (t + 120, 1)])

    def test_backup_keeps_first_and_latest(self):
        with open(self.path, "wb") as f:
            f.write(b"x")
        stamps = iter(["20260101-000000", "20260102-000000", "20260103-000000", "20260104-000000"])
        with mock.patch.object(fh.time, "strftime", side_effect=lambda fmt, *a: next(stamps)):
            for _ in range(4):
                fh.backup_file(self.path, keep=2)
        names = sorted(os.path.basename(p) for p in glob.glob(self.path + ".*.bak"))
        self.assertEqual(names, ["XAUUSD1.hst.20260101-000000.bak", "XAUUSD1.hst.20260103-000000.bak",
                                 "XAUUSD1.hst.20260104-000000.bak"])

    def test_csv_lines(self):
        csv_path = os.path.join(self.tmp.name, "x.csv")
        fh.write_csv(csv_path, store_of([fh.Bar(ts("2026-03-30 01:02"), 2000.1, 2001.0, 1999.5, 2000.25, 4)]), 2)
        with open(csv_path, newline="") as f:
            self.assertEqual(f.read(), "2026.03.30,01:02,2000.10,2001.00,1999.50,2000.25,4\r\n")


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.day = date(2026, 3, 27)

    def tearDown(self):
        self.tmp.cleanup()

    def test_download_then_cache(self):
        data = bi5(minutes("10:00", 3))
        with mock.patch.object(fh, "http_get", return_value=data) as get:
            status, raw = fh.get_day("XAUUSD", self.day, self.tmp.name)
            self.assertEqual((status, len(raw)), ("downloaded", 3 * 24))
            get.assert_called_once_with("https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/02/27/BID_candles_min_1.bi5")
            self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name)[0], "cached")
            self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name, refresh=True)[0], "downloaded")
            self.assertEqual(get.call_count, 2)

    def test_not_found_is_cached_as_empty(self):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(fh.urllib.request, "urlopen", side_effect=err):
            self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name), ("downloaded", b""))
        self.assertEqual(os.path.getsize(fh.cache_path(self.tmp.name, "XAUUSD", self.day)), 0)
        self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name, offline=True), ("cached", b""))

    def test_offline_missing_and_corrupt_cache(self):
        self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name, offline=True), ("missing", b""))
        path = fh.cache_path(self.tmp.name, "XAUUSD", self.day)
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"broken")
        with mock.patch.object(fh, "http_get", return_value=bi5(minutes("10:00", 1))):
            self.assertEqual(fh.get_day("XAUUSD", self.day, self.tmp.name)[0], "downloaded")

    def test_retry_then_fail(self):
        with mock.patch.object(fh, "http_get", side_effect=[OSError("reset"), bi5(minutes("10:00", 1))]), \
                mock.patch.object(fh.time, "sleep") as sleep:
            self.assertEqual(len(fh.download_bi5("u")[1]), 24)
            self.assertEqual(sleep.call_count, 1)
        with mock.patch.object(fh, "http_get", side_effect=OSError("down")), mock.patch.object(fh.time, "sleep"):
            with self.assertRaises(fh.FetchError):
                fh.download_bi5("u", retries=3)


class TestMain(unittest.TestCase):
    """--offline で一時キャッシュから .hst を作る通しテスト."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mt4 = os.path.join(self.tmp.name, "MT4 data")
        self.hst_dir = os.path.join(self.mt4, "history", SERVER)
        os.makedirs(self.hst_dir)
        self.cache = os.path.join(self.tmp.name, "cache")
        self.hst = os.path.join(self.hst_dir, "XAUUSD1.hst")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, day: date, records: list[tuple]) -> None:
        path = fh.cache_path(self.cache, "XAUUSD", day)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(bi5(records) if records else b"")

    def run_main(self, *extra: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["--mt4-dir", self.mt4, "--server", SERVER, "--symbol", "XAUUSD", "--from", "2026-03-27",
                "--to", "2026-03-30", "--cache-dir", self.cache, "--offline", *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fh.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_offline_with_merge_and_csv(self):
        self.put(date(2026, 3, 27), minutes("10:00", 3) + [(86340, 2_000_000, 2_000_000, 2_000_000, 2_000_000, 0.0)])
        self.put(date(2026, 3, 28), minutes("10:00", 5))  # 土曜 → 読まない
        self.put(date(2026, 3, 29), minutes("22:00", 2))  # 日曜夜（夏時間開始後 → 月曜 01:00）
        self.put(date(2026, 3, 30), minutes("00:00", 2))
        newer = ts("2026-03-30 05:00")
        fh.write_hst(self.hst, "XAUUSD", 2, store_of([bar(ts("2026-03-27 12:00"), 1), bar(newer, 1)]))
        csv_path = os.path.join(self.tmp.name, "out dir.csv")

        code, out, err = self.run_main("--csv", csv_path)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip().splitlines()[-1], self.hst)
        out.encode("cp932")  # Windows の日本語コンソールで表示できる文字だけ
        err.encode("cp932")
        header, bars = fh.read_hst(self.hst)
        self.assertEqual((header["symbol"], header["period"], header["digits"]), ("XAUUSD", 1, 2))
        self.assertEqual([b.ctm for b in bars], [
            ts("2026-03-27 12:00"), ts("2026-03-27 12:01"), ts("2026-03-27 12:02"),  # 冬時間 GMT+2
            ts("2026-03-30 01:00"), ts("2026-03-30 01:01"),  # 日曜 22:00 UTC → GMT+3
            ts("2026-03-30 03:00"), ts("2026-03-30 03:01"),
            newer])  # 既存ファイルの新しい足だけ引き継ぐ
        self.assertEqual(bars[0].open, 2000.0)  # 既存の 12:00（価格1）はダウンロード分で置き換え
        self.assertEqual(bars[-1].open, 1)
        self.assertEqual(len(glob.glob(self.hst + ".*.bak")), 1)
        with open(csv_path) as f:
            self.assertEqual(len(f.read().splitlines()), len(bars))

    def test_errors_exit_non_zero(self):
        code, _, err = self.run_main()  # キャッシュが空
        self.assertNotEqual(code, 0)
        self.assertIn("1分足がありません", err)
        self.assertFalse(os.path.exists(self.hst))
        code, _, err = self.run_main("--server", "Wrong Server")
        self.assertNotEqual(code, 0)
        self.assertIn(SERVER, err)  # 既存のフォルダ名を案内する

    def test_failed_download_does_not_write(self):
        self.put(date(2026, 3, 27), minutes("10:00", 3))
        out, err = io.StringIO(), io.StringIO()
        argv = ["--mt4-dir", self.mt4, "--server", SERVER, "--from", "2026-03-27", "--to", "2026-03-30",
                "--cache-dir", self.cache, "--workers", "2"]
        with mock.patch.object(fh, "download_bi5", side_effect=fh.FetchError("ダウンロード失敗")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fh.main(argv)
        self.assertNotEqual(code, 0)
        self.assertIn("2 日分を取得できませんでした", err.getvalue())
        self.assertFalse(os.path.exists(self.hst))


if __name__ == "__main__":
    unittest.main()
