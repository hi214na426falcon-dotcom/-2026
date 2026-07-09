"""合格戦略の推論（inference）のテスト。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.inference import infer_direction  # noqa: E402


def approved(**over):
    base = {"pair": "X", "strategy": "bollinger",
            "params": {"period": 20, "num_std": 2.0},
            "oos": {"win_rate": 0.56}}
    base.update(over)
    return base


class TestInference(unittest.TestCase):
    def test_signal_fires_down_on_upper_break(self):
        closes = [100.0] * 34 + [105.0]  # 直近が上限を大きく上抜け → 逆張りDOWN
        out = infer_direction(approved(), closes)
        self.assertEqual(out["direction"], "DOWN")
        self.assertAlmostEqual(out["confidence"], 0.56)
        self.assertEqual(out["status"], "シグナル発生")

    def test_no_signal_when_flat(self):
        closes = [100.0] * 35  # 逸脱なし → シグナルなし
        out = infer_direction(approved(), closes)
        self.assertIsNone(out["direction"])
        self.assertEqual(out["status"], "シグナル待機中")

    def test_too_few_bars(self):
        out = infer_direction(approved(), [100.0] * 10)
        self.assertIsNone(out["direction"])
        self.assertIn("バー不足", out["status"])

    def test_unknown_strategy(self):
        out = infer_direction(approved(strategy="nope"), [100.0] * 40)
        self.assertIsNone(out["direction"])
        self.assertIn("未知の戦略", out["status"])


if __name__ == "__main__":
    unittest.main()
