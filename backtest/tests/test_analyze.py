"""analyze_mt4.py / make_sample.py のユニットテスト.

実行: python3 -I -m unittest discover -s backtest/tests -v
"""
from __future__ import annotations

import contextlib
import csv
import io
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyze_mt4 as am  # noqa: E402
import make_sample as ms  # noqa: E402

STATEMENT_HTML = """<html><head><title>Statement: 12345 - Test</title></head><body>
<table>
<tr align=left><td colspan=2><b>Account: 12345</b></td><td colspan=5><b>Name: Test</b></td><td colspan=2><b>Currency: JPY</b></td></tr>
<tr align=left><td colspan=13><b>Closed Transactions:</b></td></tr>
<tr align=center><td>Ticket</td><td>Open Time</td><td>Type</td><td>Size</td><td>Item</td><td>Price</td><td>S / L</td><td>T / P</td>
<td>Close Time</td><td>Price</td><td>Commission</td><td>Taxes</td><td>Swap</td><td>Profit</td></tr>
<tr align=right><td>100</td><td>2024.01.02 00:00:00</td><td>balance</td><td colspan=10 align=left>Deposit</td><td>140 000.00</td></tr>
<tr align=right><td>101</td><td>2024.01.02 03:15:20</td><td>buy</td><td>0.01</td><td>xauusd</td><td>2050.10</td><td>0.00</td><td>0.00</td>
<td>2024.01.02 04:00:01</td><td>2052.10</td><td>-10.00</td><td>0.00</td><td>-5.00</td><td>300.00</td></tr>
<tr align=right><td>102</td><td>2024.01.03 10:00:00</td><td>sell</td><td>0.02</td><td>xauusd</td><td>2040.00</td><td>0.00</td><td>0.00</td>
<td>2024.01.03 12:30:00</td><td>2045.00</td><td>0.00</td><td>0.00</td><td>0.00</td><td>-1 500.00</td></tr>
<tr align=right><td>103</td><td>2024.01.04 09:00:00</td><td>buy limit</td><td>0.01</td><td>xauusd</td><td>2000.00</td><td>0.00</td><td>0.00</td>
<td>2024.01.04 10:00:00</td><td>2010.00</td><td colspan=4>cancelled</td></tr>
<tr align=right><td>104</td><td>2024.01.05 08:00:00</td><td>buy</td><td>0.01</td><td>xauusd</td><td>2030.00</td><td>0.00</td><td>0.00</td>
<td>2024.01.05 08:30:00</td><td>2031.00</td><td>0.00</td><td>0.00</td><td>0.00</td><td>150.00</td></tr>
<tr align=left><td colspan=13><b>Open Trades:</b></td></tr>
<tr align=right><td>105</td><td>2024.01.05 09:00:00</td><td>buy</td><td>0.01</td><td>xauusd</td><td>2030.00</td><td>0.00</td><td>0.00</td>
<td></td><td>2028.00</td><td>0.00</td><td>0.00</td><td>0.00</td><td>-300.00</td></tr>
</table></body></html>"""

CSV_TEXT = """open_time,close_time,type,lots,profit,commission,swap
2024-03-01 10:00:00,2024-03-01 10:30:00,buy,0.01,500,-20,0
2024-03-02 11:00:00,2024-03-02 11:45:00,sell,0.02,-800,0,-10
2024-03-04 09:00:00,2024-03-04 09:05:00,buy,0.01,250,0,0
"""


def mk(pnls: list[float], start: datetime = datetime(2024, 1, 1, 9), step: timedelta = timedelta(days=1),
       lots: float = 0.01) -> list[am.Trade]:
    return [am.Trade(start + i * step + timedelta(minutes=30), p, start + i * step, "buy", lots, str(i))
            for i, p in enumerate(pnls)]


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = ms.write_samples(cls.tmp.name, seed=7, years=1.0)
        cls.expected = sorted(ms.generate_trades(seed=7, years=1.0), key=lambda t: (t.close_time, t.order))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check_tester(self, ds: am.Dataset):
        self.assertEqual(ds.kind, "tester")
        self.assertEqual(len(ds.trades), len(self.expected))
        self.assertEqual(ds.deposit, ms.DEPOSIT)
        self.assertAlmostEqual(sum(t.pnl for t in ds.trades), sum(t.pnl for t in self.expected), places=2)
        self.assertEqual(ds.meta["quality"], 90.0)
        eq_abs, eq_pct = ds.meta["eq_dd"]
        self.assertGreater(eq_abs, 0)
        self.assertGreater(eq_pct, 0)
        got = {t.ticket: t for t in ds.trades}
        for e in self.expected[:50]:
            t = got[str(e.order)]
            self.assertEqual((t.open_time, t.side, t.lots), (e.open_time, e.side, e.lots))
        self.assertTrue(any("架空" in w for w in ds.warnings))

    def test_tester_english(self):
        self.check_tester(am.load_file(self.paths["en"]))

    def test_tester_japanese_cp932(self):
        with open(self.paths["ja"], "rb") as f:
            raw = f.read()
        self.assertIn("最大ドローダウン".encode("cp932"), raw)
        ds = am.load_file(self.paths["ja"])
        self.check_tester(ds)
        en = am.load_file(self.paths["en"])
        key = lambda t: (t.close_time, t.pnl, t.open_time, t.side, t.lots)  # noqa: E731
        self.assertEqual([key(t) for t in ds.trades], [key(t) for t in en.trades])
        self.assertEqual(ds.meta["eq_dd"], en.meta["eq_dd"])

    def test_statement_utf16(self):
        path = os.path.join(self.tmp.name, "statement.htm")
        with open(path, "wb") as f:
            f.write(STATEMENT_HTML.encode("utf-16"))
        ds = am.load_file(path)
        self.assertEqual(ds.kind, "statement")
        self.assertEqual(ds.currency, "JPY")
        self.assertEqual(ds.deposit, 140000.0)
        self.assertEqual([t.pnl for t in ds.trades], [285.0, -1500.0, 150.0])  # 手数料・スワップ込み
        self.assertEqual([t.side for t in ds.trades], ["buy", "sell", "buy"])
        self.assertEqual(ds.trades[1].lots, 0.02)

    def test_csv(self):
        path = os.path.join(self.tmp.name, "trades.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(CSV_TEXT)
        ds = am.load_file(path)
        self.assertEqual(ds.kind, "csv")
        self.assertEqual([t.pnl for t in ds.trades], [480.0, -810.0, 250.0])
        self.assertEqual(ds.trades[1].side, "sell")
        self.assertEqual(ds.trades[0].open_time, datetime(2024, 3, 1, 10))

    def test_end_to_end_cli(self):
        out, wcsv = os.path.join(self.tmp.name, "report.md"), os.path.join(self.tmp.name, "wf.csv")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = am.main([self.paths["en"], "--mc-runs", "200", "--is-months", "6", "--oos-months", "3",
                          "--recent-months", "6", "--out", out, "--csv", wcsv])
        self.assertEqual(rc, 0)
        with open(out, encoding="utf-8") as f:
            report = f.read()
        for heading in ("データ概要", "ウォークフォワード", "モンテカルロ", "推奨ロット", "指標の読み方", "直近6ヶ月"):
            self.assertIn(heading, report)
        self.assertIn("楽観的", report)
        with open(wcsv, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(report.count("\n| 1 |"), 2)  # WF の2つの表にウィンドウ1がある


class MetricsTests(unittest.TestCase):
    def test_hand_computed(self):
        # 残高: 1100, 1050, 1020, 1220, 1120, 1170 → 最大DD 100（1220→1120 = 8.197%）
        m = am.compute_metrics(mk([100, -50, -30, 200, -100, 50]), 1000.0)
        self.assertEqual(m["trades"], 6)
        self.assertAlmostEqual(m["net"], 170)
        self.assertAlmostEqual(m["gross_profit"], 350)
        self.assertAlmostEqual(m["gross_loss"], 180)
        self.assertAlmostEqual(m["pf"], 350 / 180)
        self.assertAlmostEqual(m["win_rate"], 50.0)
        self.assertAlmostEqual(m["max_dd"], 100)
        self.assertAlmostEqual(m["max_dd_pct"], 100 / 1220 * 100)
        self.assertEqual((m["max_consec_wins"], m["max_consec_losses"]), (1, 2))
        self.assertAlmostEqual(m["payoff"], (350 / 3) / 60)
        self.assertAlmostEqual(m["recovery"], 1.7)
        self.assertIsNotNone(m["sharpe"])

    def test_no_losses_and_empty(self):
        self.assertTrue(math.isinf(am.compute_metrics(mk([10, 20]), 100.0)["pf"]))
        m = am.compute_metrics([], 100.0)
        self.assertEqual((m["trades"], m["net"], m["pf"]), (0, 0, None))

    def test_baskets_60s(self):
        t0 = datetime(2024, 1, 1, 10)
        trades = [am.Trade(t0, -100, lots=0.01), am.Trade(t0 + timedelta(seconds=30), -200, lots=0.02),
                  am.Trade(t0 + timedelta(seconds=60), 50, lots=0.03), am.Trade(t0 + timedelta(minutes=5), 40, lots=0.02)]
        b = am.group_baskets(trades)
        self.assertEqual([x.n for x in b], [3, 1])
        self.assertAlmostEqual(b[0].pnl, -250)
        self.assertAlmostEqual(b[0].pnl_001, -250)  # 最小ロット 0.01 基準
        self.assertAlmostEqual(b[1].pnl_001, 20)  # 0.02 → 0.01 換算


class WalkForwardTests(unittest.TestCase):
    def test_window_count_5_years(self):
        trades = mk([10, -5] * 130, start=datetime(2021, 1, 4, 9), step=timedelta(days=7))
        self.assertEqual(trades[-1].close_time.year, 2025)
        wf = am.walk_forward(trades, 100000.0, 12, 3)
        self.assertEqual(len(wf), 16)  # 60ヶ月: (60 - 12) / 3
        self.assertEqual((wf[0]["is_start"], wf[0]["oos_start"]), (datetime(2021, 1, 1), datetime(2022, 1, 1)))
        self.assertEqual(wf[-1]["oos_end"], datetime(2026, 1, 1))
        self.assertEqual(len(am.wf_windows(datetime(2021, 1, 4), datetime(2021, 12, 31), 12, 3)), 0)

    def test_block_finds_bad_hour(self):
        trades = []
        for d in range(60):
            for h in (3, 9, 16):
                t = datetime(2024, 1, 1, h) + timedelta(days=d)
                trades.append(am.Trade(t + timedelta(minutes=10), -50.0 if h == 16 else 20.0, t, "buy", 0.01))
        self.assertEqual(am.best_block(trades), (16, 1))
        self.assertEqual(am.best_block(trades[:20]), (0, 0))  # 30 取引未満は停止なし
        self.assertEqual(am.block_hours((22, 4)), {22, 23, 0, 1})


class MonteCarloTests(unittest.TestCase):
    def test_seed_determinism(self):
        import random
        rng = random.Random(1)
        baskets = am.group_baskets(mk([rng.gauss(5, 50) for _ in range(300)]))
        a = am.monte_carlo(baskets, 10000.0, runs=300, seed=123)
        b = am.monte_carlo(baskets, 10000.0, runs=300, seed=123)
        c = am.monte_carlo(baskets, 10000.0, runs=300, seed=124)
        self.assertEqual(a, b)
        self.assertNotEqual(a["dd"], c["dd"])
        self.assertLessEqual(a["dd"][50], a["dd"][95])
        self.assertLessEqual(a["dd"][95], a["dd"][99])
        self.assertAlmostEqual(a["dd001"][99], a["dd"][99])  # 全取引 0.01 ロット

    def test_lot_recommendation(self):
        self.assertAlmostEqual(am.recommend_lot(140000, 10000, 30, 1.5), 0.02)  # 42000 / 15000 = 2.8
        self.assertEqual(am.recommend_lot(140000, 100000, 30, 1.5), 0.0)
        self.assertAlmostEqual(am.required_capital(0.01, 100000, 30, 1.5), 500000)


if __name__ == "__main__":
    unittest.main()
