"""昇格ゲート（promote_strategy）のテスト。"""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.promote_strategy import evaluate, metrics_from_trades, promote  # noqa: E402


@dataclass
class FakeTrade:
    index: int
    result: str


class TestMetrics(unittest.TestCase):
    def test_all_wins(self):
        trades = [FakeTrade(i, "win") for i in range(10)]
        m = metrics_from_trades(trades, payout=2.0, stake=1000, start_balance=100000)
        self.assertAlmostEqual(m["win_rate"], 1.0)
        self.assertAlmostEqual(m["edge_pt"], 50.0)  # (1.0 - 0.5)*100
        self.assertAlmostEqual(m["max_dd_pct"], 0.0)

    def test_dd(self):
        trades = [FakeTrade(0, "win"), FakeTrade(1, "loss"), FakeTrade(2, "loss")]
        m = metrics_from_trades(trades, payout=1.9, stake=1000, start_balance=100000)
        self.assertGreater(m["max_dd_pct"], 0.0)


class TestEvaluate(unittest.TestCase):
    def test_synthetic_never_passes(self):
        ev = evaluate("EURJPY", "bollinger", expiry_min=3, payout=1.90,
                      data_dir="__no_such_dir__", process="meanrevert")
        self.assertFalse(ev["oos_passed"])       # 合成データは合格させない
        self.assertTrue(ev["is_synthetic"])
        self.assertTrue(any("合成データ" in r for r in ev["reasons"]))


class TestPromote(unittest.TestCase):
    def test_writes_only_when_passed(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "approved_strategy.json")
            failing = {"oos_passed": False}
            self.assertFalse(promote(failing, out))
            self.assertFalse(os.path.exists(out))

            passing = {
                "pair": "EURJPY", "strategy": "bollinger", "params": {"period": 20},
                "expiry_min": 3, "payout": 1.90, "sessions_jst": [[17, 24], [0, 6]],
                "tz_offset_hours": 9, "oos": {"win_rate": 0.56, "edge_pt": 3.4,
                "trades": 1200, "max_dd_pct": 0.12}, "oos_passed": True,
                "is_synthetic": False, "data_source": "data/m1/EURJPY.csv",
                "generated_at": "2026-07-09T00:00:00Z",
            }
            self.assertTrue(promote(passing, out))
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertTrue(saved["oos_passed"])
            self.assertEqual(saved["pair"], "EURJPY")


if __name__ == "__main__":
    unittest.main()
