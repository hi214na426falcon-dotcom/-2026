"""fetch_history.py のユニットテスト（通信なし）.

実行: python3 -I -m unittest discover -s automation/tests -v
"""
from __future__ import annotations

import calendar
import contextlib
import glob
import io
import json
import lzma
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_history as fh  # noqa: E402

SERVER = "HFMarketsSV-Demo Server 2"
URL = "https://example.invalid/x"
JETTA, BI5 = fh.PROVIDERS["jetta"], fh.PROVIDERS["bi5"]

# 2024-02-05 の jetta 実データ（先頭4本だけ切り出したもの）
REAL_JETTA = (b'{"timestamp":1707091200000,"multiplier":0.001,"open":2039.155,"high":2039.655,"low":2037.835,'
              b'"close":2038.325,"shift":60000,"times":[0,1,1,1],"opens":[0,-740,-1220,700],'
              b'"highs":[0,-1130,-420,510],"lows":[0,-1650,840,870],"closes":[0,-1210,770,50],'
              b'"volumes":[0.03723,0.03816,0.02844,0.0144]}')


def ts(s: str) -> int:
    """'YYYY-MM-DD HH:MM' を UTC とみなしたエポック秒."""
    return calendar.timegm(datetime.strptime(s, "%Y-%m-%d %H:%M").timetuple())


def bi5(records: list[tuple]) -> bytes:
    """(秒, 始, 終, 安, 高, 出来高) のリストから Dukascopy 形式の bi5 を作る."""
    return lzma.compress(b"".join(fh.BI5_REC.pack(*r) for r in records), format=lzma.FORMAT_ALONE)


def jetta(day: date, records: list[tuple], m: float = 0.001) -> bytes:
    """同じレコードから jetta 形式の JSON を作る（最初の足が基準、以降は差分）."""
    keys = ("opens", "closes", "lows", "highs")
    d: dict = {"timestamp": fh.utc_epoch(day) * 1000, "multiplier": m, "shift": 60000, "times": [], "volumes": [],
               **{k: [] for k in keys}, **dict.fromkeys(("open", "close", "low", "high"))}
    if records:
        d.update(zip(("open", "close", "low", "high"), (x * m for x in records[0][1:5])))
        prev = (0, *records[0][1:5])
        for sec, *prices, vol in records:
            d["times"].append(sec // 60 - prev[0])
            for k, x, p in zip(keys, prices, prev[1:]):
                d[k].append(x - p)
            d["volumes"].append(vol)
            prev = (sec // 60, *prices)
    return json.dumps(d).encode()


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


def http_error(code: int, retry: str | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {"Retry-After": retry} if retry else {}, None)


class FakeResponse(io.BytesIO):
    def __init__(self, status: int, body: bytes = b"") -> None:
        super().__init__(body)
        self.status, self.headers = status, {}


class TestDaysAndUrl(unittest.TestCase):
    def test_bi5_url_month_is_zero_based(self):
        self.assertEqual(fh.day_url("XAUUSD", date(2026, 1, 5)),
                         "https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/00/05/BID_candles_min_1.bi5")
        self.assertIn("/2025/11/31/", fh.day_url("XAUUSD", date(2025, 12, 31)))

    def test_jetta_url_month_is_one_based(self):
        self.assertEqual(fh.jetta_url("XAUUSD", date(2026, 1, 5)),
                         "https://jetta.dukascopy.com/v1/candles/minute/XAU-USD/BID/2026/1/5")
        self.assertTrue(fh.jetta_url("XAU-USD", date(2025, 12, 31)).endswith("/XAU-USD/BID/2025/12/31"))

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
        self.assertEqual(fh.decode_bi5(b"", date(2026, 1, 5)), fh.DayData([]))


class TestJetta(unittest.TestCase):
    def test_real_sample(self):
        data = fh.decode_jetta(REAL_JETTA, date(2024, 2, 5))
        self.assertEqual(data.divisor, 1000)
        self.assertEqual(data.recs[0], (0, 2039155, 2038325, 2037835, 2039655, 0.03723))
        self.assertEqual(data.recs[1], (60, 2038415, 2037115, 2036185, 2038525, 0.03816))
        self.assertEqual([r[0] for r in data.recs], [0, 60, 120, 180])
        b = fh.day_bars(date(2024, 2, 5), data.recs, data.divisor, 3)[1]
        self.assertEqual((b.ctm, b.open, b.high, b.low, b.close),
                         (ts("2024-02-05 02:01"), 2038.415, 2038.525, 2036.185, 2037.115))  # 冬時間 GMT+2

    def test_round_trip_with_gap_at_start(self):
        recs = [(82800, 2_053_025, 2_052_975, 2_052_895, 2_053_065, 0.5),  # 休場明け 23:00 UTC から
                (82860, 2_052_995, 2_053_100, 2_052_900, 2_053_200, 0.2), (83040, 2_053_000, 2_053_010, 2_052_990,
                                                                          2_053_020, 0.1)]
        data = fh.decode_jetta(jetta(date(2023, 12, 25), recs), date(2023, 12, 25))
        self.assertEqual(data.recs, recs)

    def test_empty_and_invalid(self):
        day = date(2024, 2, 3)
        self.assertEqual(fh.decode_jetta(b"", day).recs, [])
        self.assertEqual(fh.decode_jetta(jetta(day, []), day).recs, [])  # 土曜: times が空、基準値は null
        bad = json.loads(REAL_JETTA)
        bad["opens"] = bad["opens"][:2]
        for body in (b"<html></html>", b"[]", json.dumps(bad).encode(), REAL_JETTA.replace(b'"shift":60000', b'"shift":0')):
            with self.assertRaises(ValueError):
                fh.decode_jetta(body, day)

    def test_check_scale(self):
        bars = [bar(60 * i, 4000.0) for i in range(5)]
        fh.check_scale(bars, 1000)
        fh.check_scale(bars, 1000, prev_close=3900.0)
        with self.assertRaises(ValueError):
            fh.check_scale([bar(0, 40.0)], 100000)  # 範囲外
        with self.assertRaises(ValueError):
            fh.check_scale(bars, 1000, prev_close=400.0)  # 前の日から10倍に飛んだ


class TestHttp(unittest.TestCase):
    def test_status_handling(self):
        with mock.patch.object(fh.urllib.request, "urlopen", return_value=FakeResponse(202)):
            with self.assertRaises(fh.HttpStatus) as cm:
                fh.http_get(URL)
            self.assertEqual(cm.exception.code, 202)
        with mock.patch.object(fh.urllib.request, "urlopen", return_value=FakeResponse(200, b"ok")):
            self.assertEqual(fh.http_get(URL), b"ok")
        with mock.patch.object(fh.urllib.request, "urlopen", side_effect=http_error(404)):
            self.assertEqual(fh.http_get(URL), b"")
        with mock.patch.object(fh.urllib.request, "urlopen", side_effect=http_error(503, "7")):
            with self.assertRaises(fh.HttpStatus) as cm:
                fh.http_get(URL)
            self.assertEqual((cm.exception.code, cm.exception.retry_after), (503, 7.0))

    def test_retry_honors_retry_after(self):
        day = date(2026, 3, 27)
        with mock.patch.object(fh, "http_get", side_effect=[fh.HttpStatus(503, 7.0), jetta(day, minutes("10:00", 1))]), \
                mock.patch.object(fh.time, "sleep") as sleep:
            self.assertEqual(len(fh.fetch_day(JETTA, "XAUUSD", day)[1].recs), 1)
        self.assertTrue(7 <= sleep.call_args.args[0] < 8)

    def test_no_retry_on_forbidden_and_429_callback(self):
        day = date(2026, 3, 27)
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(403)) as get, \
                mock.patch.object(fh.time, "sleep"):
            with self.assertRaises(fh.FetchError):
                fh.fetch_day(JETTA, "XAUUSD", day)
            self.assertEqual(get.call_count, 1)
        hit = mock.Mock()
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(429, 500.0)) as get, \
                mock.patch.object(fh.time, "sleep") as sleep:
            with self.assertRaises(fh.FetchError):
                fh.fetch_day(JETTA, "XAUUSD", day, hit, retries=2)
            self.assertEqual(get.call_count, 2)
        hit.assert_called()
        self.assertLessEqual(sleep.call_args.args[0], fh.MAX_WAIT + 1)  # Retry-After は上限で頭打ち

    def test_retry_on_network_error_and_corrupt_data(self):
        day = date(2026, 3, 27)
        with mock.patch.object(fh, "http_get", side_effect=[OSError("reset"), b"broken", bi5(minutes("10:00", 1))]), \
                mock.patch.object(fh.time, "sleep") as sleep:
            self.assertEqual(len(fh.fetch_day(BI5, "XAUUSD", day)[1].recs), 1)
            self.assertEqual(sleep.call_count, 2)
        with mock.patch.object(fh, "http_get", side_effect=OSError("down")), mock.patch.object(fh.time, "sleep"):
            with self.assertRaises(fh.FetchError):
                fh.fetch_day(BI5, "XAUUSD", day, retries=3)


class TestFetcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.day = date(2026, 3, 27)
        self.sleep = mock.patch.object(fh.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.tmp.cleanup()

    def fetcher(self, *names: str, **kw) -> fh.Fetcher:
        return fh.Fetcher([fh.PROVIDERS[n] for n in names or ("jetta", "bi5")], self.tmp.name, "XAUUSD", **kw)

    def path(self, ext: str = ".json") -> str:
        return fh.cache_path(self.tmp.name, "XAUUSD", self.day, ext)

    def put(self, data: bytes, ext: str = ".bi5") -> None:
        os.makedirs(os.path.dirname(self.path(ext)), exist_ok=True)
        with open(self.path(ext), "wb") as f:
            f.write(data)

    def test_download_then_cache_then_refresh(self):
        f = self.fetcher()
        with mock.patch.object(fh, "http_get", return_value=jetta(self.day, minutes("10:00", 3))) as get:
            res = f.get_day(self.day)
            self.assertEqual((res.status, len(res.data.recs), res.note), ("downloaded", 3, "jetta"))
            get.assert_called_once_with("https://jetta.dukascopy.com/v1/candles/minute/XAU-USD/BID/2026/3/27")
            self.assertEqual(f.get_day(self.day).status, "cached")
            self.assertEqual(f.get_day(self.day, recent=True).status, "downloaded")
            self.assertEqual(get.call_count, 2)

    def test_recent_day_failure_uses_cache(self):
        self.put(bi5(minutes("10:00", 3)))
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(503)):
            res = self.fetcher().get_day(self.day, recent=True)
        self.assertEqual((res.status, len(res.data.recs)), ("stale", 3))
        self.assertIn("前回の取得分", res.note)
        self.assertGreater(os.path.getsize(self.path(".bi5")), 0)

    def test_recent_empty_does_not_overwrite_cache(self):
        self.put(bi5(minutes("10:00", 3)))
        with mock.patch.object(fh, "http_get", return_value=b""):
            res = self.fetcher().get_day(self.day, recent=True)
        self.assertEqual((res.status, len(res.data.recs)), ("stale", 3))
        self.assertGreater(os.path.getsize(self.path(".bi5")), 0)
        self.assertFalse(os.path.exists(self.path(".json")))

    def test_empty_cached_only_when_not_recent(self):
        with mock.patch.object(fh, "http_get", return_value=b""):
            self.assertEqual(self.fetcher().get_day(self.day, recent=True), ("downloaded", fh.DayData([]), "jetta"))
            self.assertFalse(os.path.exists(self.path()))  # 直近の「データなし」は次回また取得
            self.assertEqual(self.fetcher().get_day(self.day).status, "downloaded")
        self.assertEqual(os.path.getsize(self.path()), 0)
        self.assertEqual(self.fetcher(offline=True).get_day(self.day), ("cached", fh.DayData([]), ""))

    def test_fallback_to_bi5_and_one_file_per_day(self):
        def get(url):
            if "jetta" in url:
                raise fh.HttpStatus(403)
            return bi5(minutes("10:00", 2))
        with mock.patch.object(fh, "http_get", side_effect=get):
            res = self.fetcher().get_day(self.day)
        self.assertEqual((res.status, res.note, len(res.data.recs)), ("downloaded", "bi5", 2))
        self.assertTrue(os.path.exists(self.path(".bi5")))
        with mock.patch.object(fh, "http_get", return_value=jetta(self.day, minutes("10:00", 4))):
            self.assertEqual(len(self.fetcher().get_day(self.day, recent=True).data.recs), 4)
        self.assertFalse(os.path.exists(self.path(".bi5")))  # 新しく取った jetta 分だけ残す
        self.assertEqual(len(self.fetcher("bi5", offline=True).get_day(self.day).data.recs), 4)

    def test_offline_missing_and_corrupt_cache(self):
        self.assertEqual(self.fetcher(offline=True).get_day(self.day).status, "missing")
        self.put(b"broken")
        with mock.patch.object(fh, "http_get", return_value=bi5(minutes("10:00", 1))):
            self.assertEqual(self.fetcher("bi5").get_day(self.day).status, "downloaded")

    def test_breaker(self):
        f = self.fetcher(limit=2)
        f.record("jetta", "x")
        f.record("jetta")  # 成功で数え直し
        f.record("jetta", "x")
        self.assertEqual([p.name for p in f.alive()], ["jetta", "bi5"])
        f.record("jetta", "HTTP 503")
        f.record("jetta")  # 止めた後の成功では戻さない
        self.assertEqual([p.name for p in f.alive()], ["bi5"])
        self.assertEqual(f.errors["jetta"], "HTTP 503")


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
        self.assertEqual((s.close_at(60), s.close_at(61)), (4000.5, None))

    def test_scan_returns_overlap_and_newer(self):
        t = ts("2026-03-30 10:00")
        fh.write_hst(self.path, "XAUUSD", 2, store_of([bar(t - 600, 1), bar(t, 1), bar(t + 60, 1), bar(t + 120, 1)]))
        overlap, newer = fh.scan_hst(self.path, t - 60, t)
        self.assertEqual([b.ctm for b in overlap], [t])
        self.assertEqual([b.ctm for b in newer], [t + 60, t + 120])
        s = store_of([bar(t - 60), bar(t)])
        s.add(newer)
        self.assertEqual([(b.ctm, b.open) for b in s.bars()], [(t - 60, 2000), (t, 2000), (t + 60, 1), (t + 120, 1)])

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


class TestCheckAgainstExisting(unittest.TestCase):
    """ブローカーの既存ヒストリーとの照合（価格の桁・時差）."""

    def setUp(self):
        self.bars = [bar(ts("2026-03-27 12:00") + 60 * i, 2000 + 0.01 * i) for i in range(600)]
        self.store = store_of(self.bars)

    def test_matching(self):
        note = fh.check_against_existing(self.store, [b._replace(close=b.close + 0.3) for b in self.bars])
        self.assertIn("照合しました（600 本", note)
        self.assertNotIn("ずれて", note)

    def test_too_few_bars(self):
        self.assertIn("照合はしていません", fh.check_against_existing(self.store, self.bars[:10]))

    def test_wrong_scale_and_shift_abort(self):
        with self.assertRaisesRegex(fh.FetchError, "倍"):
            fh.check_against_existing(self.store, [b._replace(close=b.close / 10) for b in self.bars])
        with self.assertRaisesRegex(fh.FetchError, "1 時間ずれ"):
            fh.check_against_existing(self.store, [b._replace(ctm=b.ctm + 3600) for b in self.bars])

    def test_single_shifted_day_is_reported(self):
        day2 = [bar(ts("2026-03-30 12:00") + 60 * i, 2010 + 0.01 * i) for i in range(400)]
        self.store.add(day2)
        note = fh.check_against_existing(self.store, self.bars + [b._replace(ctm=b.ctm + 3600) for b in day2])
        self.assertIn("1時間ずれているようです", note)
        self.assertIn("2026-03-30", note)
        self.assertNotIn("2026-03-27", note.split("注意")[1])


class TestMain(unittest.TestCase):
    """main() の通しテスト（キャッシュ・通信はモック）."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mt4 = os.path.join(self.tmp.name, "MT4 data")
        self.hst_dir = os.path.join(self.mt4, "history", SERVER)
        os.makedirs(self.hst_dir)
        self.cache = os.path.join(self.tmp.name, "cache")
        self.hst = os.path.join(self.hst_dir, "XAUUSD1.hst")
        self.sleep = mock.patch.object(fh.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, day: date, records: list[tuple], ext: str = ".bi5") -> None:
        path = fh.cache_path(self.cache, "XAUUSD", day, ext)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write((bi5(records) if records else b"") if ext == ".bi5" else jetta(day, records))

    def run_main(self, *extra: str, start: str = "2026-03-27", end: str = "2026-03-30",
                 offline: bool = True) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        argv = ["--mt4-dir", self.mt4, "--server", SERVER, "--symbol", "XAUUSD", "--from", start,
                "--to", end, "--cache-dir", self.cache, *(["--offline"] if offline else []), *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fh.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_end_to_end_offline_with_merge_and_csv(self):
        self.put(date(2026, 3, 27), minutes("10:00", 3) + [(86340, 2_000_000, 2_000_000, 2_000_000, 2_000_000, 0.0)])
        self.put(date(2026, 3, 28), minutes("10:00", 5))  # 土曜 → 読まない
        self.put(date(2026, 3, 29), minutes("22:00", 2), ".json")  # 日曜夜（夏時間開始後 → 月曜 01:00）、jetta 形式
        self.put(date(2026, 3, 30), minutes("00:00", 2))
        newer = ts("2026-03-30 05:00")
        fh.write_hst(self.hst, "XAUUSD", 2, store_of([bar(ts("2026-03-27 12:00"), 1), bar(newer, 1)]))
        csv_path = os.path.join(self.tmp.name, "out dir.csv")

        code, out, err = self.run_main("--csv", csv_path)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip().splitlines()[-1], self.hst)
        out.encode("cp932")  # Windows の日本語コンソールで表示できる文字だけ
        err.encode("cp932")
        self.assertIn("照合はしていません", out)  # 重なりが1本だけなので照合しない
        header, bars = fh.read_hst(self.hst)
        self.assertEqual((header["symbol"], header["period"], header["digits"]), ("XAUUSD", 1, 2))
        self.assertEqual([b.ctm for b in bars], [
            ts("2026-03-27 12:00"), ts("2026-03-27 12:01"), ts("2026-03-27 12:02"),  # 冬時間 GMT+2
            ts("2026-03-30 01:00"), ts("2026-03-30 01:01"),  # 日曜 22:00 UTC → GMT+3
            ts("2026-03-30 03:00"), ts("2026-03-30 03:01"),
            newer])  # 既存ファイルの新しい足だけ引き継ぐ
        self.assertEqual(bars[0].open, 2000.0)  # 既存の 12:00（価格1）はダウンロード分で置き換え
        self.assertEqual(bars[3].open, 2000.0)  # jetta 形式のキャッシュも同じ価格になる
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

    def test_future_end_is_clamped_to_yesterday(self):
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        code, _, err = self.run_main(start=yesterday.isoformat(), end="2099-01-01")
        self.assertIn(f"{yesterday} までにしました", err)
        self.assertNotEqual(code, 0)  # キャッシュが空

    def test_failed_download_does_not_write(self):
        self.put(date(2026, 3, 27), minutes("10:00", 3))
        with mock.patch.object(fh, "fetch_day", side_effect=fh.FetchError("HTTP 500")):
            code, _, err = self.run_main("--workers", "2", offline=False)
        self.assertNotEqual(code, 0)
        self.assertIn("2 日分を取得できませんでした", err)
        self.assertFalse(os.path.exists(self.hst))

    def test_circuit_breaker_stops_early(self):
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(503)) as get:
            code, _, err = self.run_main("--workers", "2", start="2026-01-05", end="2026-03-27", offline=False)
        self.assertEqual(code, 1)
        self.assertIn("Dukascopy に接続できません", err)
        self.assertIn("HTTP 503", err)
        days = len(fh.trading_days(date(2026, 1, 5), date(2026, 3, 27)))
        self.assertLessEqual(get.call_count, (fh.BREAKER_LIMIT + 4) * fh.RETRIES * 2)  # 全日を試さない
        self.assertLess(get.call_count, days * fh.RETRIES * 2 / 3)
        self.assertFalse(os.path.exists(self.hst))

    def test_rate_limit_switches_to_serial_and_waits(self):
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(429, 7.0)):
            code, _, err = self.run_main(start="2026-03-02", end="2026-03-27", offline=False)
        self.assertEqual(code, 1)
        self.assertIn("1本ずつ", err)
        self.assertTrue(any(7 <= c.args[0] < 8 for c in self.sleep.call_args_list))

    def test_recent_day_refresh_failure_falls_back_to_cache(self):
        day = datetime.now(timezone.utc).date() - timedelta(days=1)
        day -= timedelta(days=day.weekday() == 5)  # 土曜は対象外なので金曜に
        self.put(day, minutes("10:00", 3))
        with mock.patch.object(fh, "http_get", side_effect=fh.HttpStatus(503)):
            code, out, err = self.run_main(start=day.isoformat(), end=day.isoformat(), offline=False)
        self.assertEqual(code, 0, err)
        self.assertIn("前回の取得分を使いました", out)
        self.assertEqual(len(fh.read_hst(self.hst)[1]), 3)

    def existing_from(self, transform) -> bytes:
        """2026-03-27 の 400 本をキャッシュに置き、同じ足を transform した既存 .hst を作る."""
        self.put(date(2026, 3, 27), minutes("10:00", 400))
        bars = fh.day_bars(date(2026, 3, 27), minutes("10:00", 400), 1000)
        fh.write_hst(self.hst, "XAUUSD", 2, store_of([transform(b) for b in bars]))
        with open(self.hst, "rb") as f:
            return f.read()

    def test_broker_check_aborts_on_wrong_scale(self):
        before = self.existing_from(lambda b: b._replace(close=b.close / 10))
        code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("倍", err)
        with open(self.hst, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(glob.glob(self.hst + ".*.bak"), [])
        code, out, err = self.run_main("--no-check")
        self.assertEqual(code, 0, err)

    def test_broker_check_passes(self):
        self.existing_from(lambda b: b._replace(close=b.close + 0.2))
        code, out, err = self.run_main()
        self.assertEqual(code, 0, err)
        self.assertIn("既存ヒストリーと照合しました（400 本", out)

    def test_backup_failure_is_reported_in_japanese(self):
        before = self.existing_from(lambda b: b)
        with mock.patch.object(fh.shutil, "copy2", side_effect=OSError(28, "No space left on device")):
            code, _, err = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("バックアップできない", err)
        with open(self.hst, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_csv_failure_still_succeeds(self):
        self.put(date(2026, 3, 27), minutes("10:00", 3))
        code, out, err = self.run_main("--csv", os.path.join(self.tmp.name, "no such dir", "x.csv"))
        self.assertEqual(code, 0, err)
        self.assertIn("CSV を保存できませんでした", out)
        self.assertEqual(out.strip().splitlines()[-1], self.hst)


if __name__ == "__main__":
    unittest.main()
