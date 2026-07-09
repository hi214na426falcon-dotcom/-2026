"""predict_server の予測ゲート＆推論接続のテスト。"""

import json
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "overlay", "server"))

import predict_server as ps  # noqa: E402


def write_approved(path, pair="EURJPY"):
    approved = {
        "pair": pair, "strategy": "bollinger", "params": {"period": 20, "num_std": 2.0},
        "expiry_min": 3, "payout": 1.90, "sessions_jst": [[0, 24]],
        "tz_offset_hours": 9, "oos": {"win_rate": 0.56, "edge_pt": 3.4,
        "trades": 1200, "max_dd_pct": 0.12}, "oos_passed": True,
        "is_synthetic": False, "data_source": "x", "generated_at": "2026-07-09T00:00:00Z",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(approved, f)


def write_csv(path):
    # 直近が上限を上抜け → 逆張りDOWN が最終バーで発火するデータ
    closes = [100.0] * 34 + [105.0]
    with open(path, "w", encoding="utf-8") as f:
        f.write("time,open,high,low,close,volume\n")
        for i, c in enumerate(closes):
            f.write(f"2026-07-10T10:{i:02d}:00,{c},{c},{c},{c},0\n")


class TestGetPrediction(unittest.TestCase):
    def test_no_approved_returns_null(self):
        with tempfile.TemporaryDirectory() as d:
            out = ps.get_prediction("EURJPY", approved_path=os.path.join(d, "none.json"),
                                    data_dir=d)
            self.assertIsNone(out["direction"])
            self.assertIn("検証済み戦略なし", out["status"])

    def test_prediction_when_approved_and_data(self):
        with tempfile.TemporaryDirectory() as d:
            ap = os.path.join(d, "approved_strategy.json")
            write_approved(ap, "EURJPY")
            write_csv(os.path.join(d, "EURJPY.csv"))
            out = ps.get_prediction("EURJPY", approved_path=ap, data_dir=d)
            self.assertEqual(out["direction"], "DOWN")
            self.assertAlmostEqual(out["confidence"], 0.56)

    def test_pair_mismatch_no_direction(self):
        with tempfile.TemporaryDirectory() as d:
            ap = os.path.join(d, "approved_strategy.json")
            write_approved(ap, "EURJPY")
            write_csv(os.path.join(d, "EURJPY.csv"))
            out = ps.get_prediction("USDJPY", approved_path=ap, data_dir=d)
            self.assertIsNone(out["direction"])
            self.assertIn("EURJPY", out["status"])

    def test_approved_but_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            ap = os.path.join(d, "approved_strategy.json")
            write_approved(ap, "EURJPY")
            out = ps.get_prediction("EURJPY", approved_path=ap, data_dir=d)
            self.assertIsNone(out["direction"])
            self.assertIn("相場データなし", out["status"])


if __name__ == "__main__":
    unittest.main()
