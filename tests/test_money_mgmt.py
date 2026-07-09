"""資金管理（連勝・ボーナスステージ・逆マーチン）のテスト。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.money_mgmt import MoneyManager, simulate_money_management  # noqa: E402


class TestMoneyManager(unittest.TestCase):
    def test_base_stake_before_bonus(self):
        mm = MoneyManager()
        self.assertEqual(mm.next_stake, 1000.0)
        mm.record("win")
        mm.record("win")
        self.assertEqual(mm.streak, 2)
        self.assertFalse(mm.bonus_active)
        self.assertEqual(mm.next_stake, 1000.0)  # まだ通常額

    def test_bonus_enters_on_third_win(self):
        mm = MoneyManager()  # ladder [1.5, 2.0, 3.0]
        mm.record("win")
        mm.record("win")
        mm.record("win")
        self.assertTrue(mm.bonus_active)
        self.assertEqual(mm.bonus_level, 1)
        self.assertAlmostEqual(mm.next_stake, 1500.0)  # 1000 * 1.5

    def test_reverse_martingale_ladder(self):
        mm = MoneyManager()
        for _ in range(4):
            mm.record("win")  # streak4 -> level2
        self.assertEqual(mm.bonus_level, 2)
        self.assertAlmostEqual(mm.next_stake, 2000.0)
        mm.record("win")  # streak5 -> level3 (top)
        self.assertEqual(mm.bonus_level, 3)
        self.assertAlmostEqual(mm.next_stake, 3000.0)

    def test_cash_out_at_top(self):
        mm = MoneyManager()
        for _ in range(5):
            mm.record("win")  # level3 (top)
        self.assertTrue(mm.at_bonus_top)
        mm.record("win")  # 最高段で勝ち → 利食いして通常へ
        self.assertFalse(mm.bonus_active)
        self.assertEqual(mm.next_stake, 1000.0)
        self.assertEqual(mm.streak, 6)  # 連勝カウントは継続

    def test_loss_resets_no_martingale(self):
        mm = MoneyManager()
        for _ in range(4):
            mm.record("win")
        self.assertTrue(mm.bonus_active)
        mm.record("loss")
        # 負けたら賭け金は上げず base に戻る（通常マーチン禁止の担保）
        self.assertEqual(mm.streak, 0)
        self.assertFalse(mm.bonus_active)
        self.assertEqual(mm.next_stake, 1000.0)

    def test_tie_is_neutral(self):
        mm = MoneyManager()
        mm.record("win")
        mm.record("tie")
        self.assertEqual(mm.streak, 1)  # 引き分けは連勝を切らない
        self.assertEqual(mm.next_stake, 1000.0)

    def test_snapshot_keys(self):
        mm = MoneyManager()
        snap = mm.snapshot()
        for k in ("streak", "bonus_active", "bonus_level", "bonus_threshold", "next_stake"):
            self.assertIn(k, snap)


class TestSimulate(unittest.TestCase):
    def test_all_wins_profit(self):
        res = simulate_money_management(["win"] * 10, payout=1.90, start_balance=100000)
        self.assertGreater(res.total_pnl, 0)
        self.assertEqual(len(res.balances), 11)
        self.assertGreaterEqual(res.max_streak, 10)
        self.assertGreaterEqual(res.bonus_entries, 1)

    def test_all_losses_bounded(self):
        # 全敗でも逆マーチンは発動しない（負けは常に base_stake だけ失う）
        res = simulate_money_management(["loss"] * 10, payout=1.90, start_balance=100000)
        self.assertAlmostEqual(res.total_pnl, -10000.0)  # 1000 * 10


if __name__ == "__main__":
    unittest.main()
