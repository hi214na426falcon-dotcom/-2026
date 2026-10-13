import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_brief as db  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FF_WEEK = os.path.join(FIXTURES, "ff_week.json")


def load_cfg() -> dict:
    with open(db.DEFAULT_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def ev(title, country="USD", impact="High", when="2026-10-14T08:30:00-04:00"):
    return db.Event(title, country, impact, datetime.fromisoformat(when))


def yahoo_chart(closes):
    ts0 = int(datetime(2026, 4, 1, 17, tzinfo=db.NY).timestamp())
    n = len(closes)
    return {"chart": {"result": [{
        "timestamp": [ts0 + i * 86400 for i in range(n)],
        "indicators": {"quote": [{
            "open": closes,
            "high": [c + 30 for c in closes],
            "low": [c - 30 for c in closes],
            "close": closes,
        }]},
    }]}}


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def test_tiers(self):
        cases = {
            ("Non-Farm Employment Change", "USD", "High"): "red",
            ("Core CPI m/m", "USD", "High"): "red",
            ("Federal Funds Rate", "USD", "High"): "red",
            ("ADP Non-Farm Employment Change", "USD", "High"): "yellow",
            ("PPI m/m", "USD", "High"): "yellow",
            ("Fed Chair Warsh Speaks", "USD", "Medium"): "yellow",
            ("Prelim UoM Consumer Sentiment", "USD", "Medium"): "info",
            ("Pending Home Sales m/m", "USD", "Low"): None,
            ("CPI y/y", "GBP", "High"): "other",
            ("Bank Holiday", "USD", "Holiday"): "holiday",
            ("Bank Holiday", "JPY", "Holiday"): None,
        }
        for (title, cur, impact), want in cases.items():
            with self.subTest(title=title, cur=cur):
                self.assertEqual(db.classify(ev(title, cur, impact), self.cfg), want)

    def test_title_ja(self):
        self.assertEqual(db.title_ja(ev("Core CPI m/m")), "米 コアCPI 前月比")
        self.assertEqual(db.title_ja(ev("Fed Chair Warsh Speaks")), "米 FRB議長 Warsh 発言")
        self.assertEqual(db.title_ja(ev("Something New m/m")), "米 Something New m/m")


class TimeTest(unittest.TestCase):
    def test_server_time_follows_eu_dst(self):
        cases = [
            ("2026-10-14T21:30+09:00", "2026-10-14 15:30"),  # EEST (GMT+3)
            ("2026-10-29T03:00+09:00", "2026-10-28 20:00"),  # EU DST ended 10/25, US not yet
            ("2026-11-06T22:30+09:00", "2026-11-06 15:30"),  # EET (GMT+2)
        ]
        for jst, want in cases:
            got = db.to_server(datetime.fromisoformat(jst)).strftime("%Y-%m-%d %H:%M")
            self.assertEqual(got, want, jst)

    def test_seasonal(self):
        cfg = load_cfg()
        self.assertIsNotNone(db.seasonal_reason(date(2026, 12, 28), cfg))
        self.assertIsNotNone(db.seasonal_reason(date(2027, 1, 2), cfg))
        self.assertIsNone(db.seasonal_reason(date(2027, 1, 5), cfg))


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.events = db.load_events(FF_WEEK)

    def test_cpi_day_is_red_with_merged_window(self):
        plan = db.plan_day(date(2026, 10, 14), self.events, self.cfg)
        self.assertEqual(plan.level, db.RED)
        self.assertEqual(plan.stop_all_day, [])
        # CPI 21:30 JST: 19:30〜翌00:30, FRB議長 02:00 JST: 01:30〜03:00 → 別ウィンドウ
        self.assertEqual(len(plan.windows), 2)
        self.assertIn("JST 19:30〜翌00:30（サーバー 13:30〜18:30）", db.span_text(plan.windows[0]))

    def test_fomc_window_crosses_midnight(self):
        plan = db.plan_day(date(2026, 10, 28), self.events, self.cfg)
        self.assertEqual(len(plan.windows), 1)
        self.assertEqual(db.span_text(plan.windows[0]), "JST 01:00〜06:30（サーバー 18:00〜23:30）")

    def test_holiday_is_caution_not_stop(self):
        plan = db.plan_day(date(2026, 10, 12), self.events, self.cfg)
        self.assertEqual(plan.level, db.YELLOW)
        self.assertEqual(plan.stop_all_day, [])
        self.assertIn("祝日", db.headline(plan))

    def test_stop_dates_and_quiet_day(self):
        self.assertTrue(db.plan_day(date(2026, 11, 26), [], self.cfg).stop_all_day)
        quiet = db.plan_day(date(2026, 10, 13), self.events, self.cfg)
        self.assertEqual(quiet.level, db.GREEN)

    def test_static_schedule_fills_future_only(self):
        static = db.load_static_schedule(db.DEFAULT_SCHEDULE)
        merged = db.merge_with_static(self.events, static)
        titles = [(e.title, e.time.date()) for e in merged]
        self.assertIn(("Non-Farm Employment Change", date(2026, 11, 6)), titles)
        # 既にライブデータがある 10/14 の CPI は重複しない
        self.assertEqual(sum(1 for e in merged if e.title == "CPI m/m" and e.time.date() == date(2026, 10, 14)), 1)
        self.assertTrue(db.merge_with_static(None, static))


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.events = db.load_events(FF_WEEK)

    def check_limits(self, payload):
        emb = payload["embeds"][0]
        self.assertLessEqual(len(emb.get("fields", [])), 25)
        for f in emb.get("fields", []):
            self.assertLessEqual(len(f["value"]), 1024)
        total = len(emb["title"]) + len(emb["description"]) + sum(len(f["name"]) + len(f["value"]) for f in emb.get("fields", []))
        self.assertLess(total, 6000)

    def test_cpi_day_payload(self):
        now = datetime.fromisoformat("2026-10-14T05:58+09:00")
        vol = db.volatility_stats([
            (date(2026, 4, 1) + timedelta(days=i), 4000.0, 4030.0, 3970.0, 4000.0 + i) for i in range(60)])
        payload = db.build_daily_payload(now, self.events, self.cfg, vol, 158.4, None)
        self.check_limits(payload)
        text = db.payload_to_text(payload)
        self.assertIn("10/14(水)", text)
        self.assertIn("🔴 重要指標あり", text)
        self.assertIn("21:30 米 消費者物価指数（CPI） 前月比", text)
        self.assertIn("翌02:00 米 FRB議長 Warsh 発言", text)
        self.assertIn("🌐 その他の主要国", text)
        self.assertIn("想定リスク", text)
        self.assertEqual(payload["embeds"][0]["color"], db.LEVEL_META[db.RED][2])

    def test_calendar_failure_payload(self):
        now = datetime.fromisoformat("2026-10-14T05:58+09:00")
        payload = db.build_daily_payload(now, None, self.cfg, None, None, "boom")
        self.assertIn("取得に失敗", payload["embeds"][0]["description"])

    def test_volatility_levels(self):
        calm = [(date(2026, 1, 1) + timedelta(days=i), 1, 31.0, 1.0, 16.0) for i in range(60)]
        stats = db.volatility_stats(calm)
        self.assertAlmostEqual(stats["atr14"], 30.0)
        self.assertEqual(db.vol_assessment(stats, self.cfg)[0], db.GREEN)
        spike = calm[:-1] + [(calm[-1][0], 1, 120.0, 1.0, 60.0)]
        self.assertEqual(db.vol_assessment(db.volatility_stats(spike), self.cfg)[0], db.RED)

    def test_load_bars_from_yahoo_format(self):
        path = os.path.join(FIXTURES, "_tmp_chart.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(yahoo_chart([4000.0 + i for i in range(40)]), f)
        try:
            bars = db.load_bars("GC=F", path)
        finally:
            os.remove(path)
        self.assertEqual(len(bars), 40)
        self.assertAlmostEqual(db.volatility_stats(bars)["atr14"], 60.0)


class MainTest(unittest.TestCase):
    def run_main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = db.main(list(args))
        return code, buf.getvalue()

    def test_dry_run(self):
        code, out = self.run_main("--dry-run", "--no-price", "--fixture", FF_WEEK, "--now", "2026-10-15T05:58+09:00")
        self.assertEqual(code, 0)
        self.assertIn("10/15(木)", out)
        self.assertIn("🟡 指標前後だけ停止して稼働", out)

    def test_weekend_skip(self):
        code, out = self.run_main("--dry-run", "--no-price", "--fixture", FF_WEEK, "--now", "2026-10-17T05:58+09:00")
        self.assertEqual(code, 0)
        self.assertIn("土日", out)


if __name__ == "__main__":
    unittest.main()
