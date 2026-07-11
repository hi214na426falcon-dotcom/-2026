"""ウォークフォワード素材生成の基礎部品のテスト。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.walkforward import build_grid, slot_index_jst  # noqa: E402


class TestGrid(unittest.TestCase):
    def test_grid_size_and_determinism(self):
        g1, g2 = build_grid(), build_grid()
        self.assertEqual(g1, g2)  # 事前登録＝決定論的
        self.assertEqual(len(g1), 96)  # 16戦略設定 × 反転2 × expiry3
        strats = {c["strategy"] for c in g1}
        self.assertEqual(strats, {"bollinger", "rsi", "ma_cross", "macd"})

    def test_slot_index(self):
        # UTC 8時 = JST 17時 → スロット0 (17-20)
        self.assertEqual(slot_index_jst("2024-01-01T08:00:00+00:00"), 0)
        # UTC 12時 = JST 21時 → スロット1 (20-24)
        self.assertEqual(slot_index_jst("2024-01-01T12:00:00+00:00"), 1)
        # UTC 15時 = JST 0時 → スロット2 (0-3)
        self.assertEqual(slot_index_jst("2024-01-01T15:00:00+00:00"), 2)
        # UTC 18時 = JST 3時 → スロット3 (3-6)
        self.assertEqual(slot_index_jst("2024-01-01T18:00:00+00:00"), 3)
        # UTC 21時 = JST 6時 → スロット外
        self.assertIsNone(slot_index_jst("2024-01-01T21:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
