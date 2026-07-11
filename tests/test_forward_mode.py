"""フォワードテスト・モード（5,000円資金管理＋ピック配信）のテスト。"""

import json
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "overlay", "server"))

import predict_server as ps  # noqa: E402


def make_pick(pair="CHFJPY", slot=(17, 20), lcb=0.55, expiry=5):
    return {"pair": pair, "strategy": "bollinger",
            "params": {"period": 20, "num_std": 2.0}, "invert": False,
            "expiry_min": expiry, "slot_jst": list(slot),
            "train": {"days": 84, "n": 200, "win_rate": 0.60, "lcb": lcb},
            "adopted": True}


class TestBank(unittest.TestCase):
    def setUp(self):
        self._log = tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl")
        self._log.close()
        os.unlink(self._log.name)
        self._orig_log = ps.FORWARD_LOG
        ps.FORWARD_LOG = self._log.name
        ps.reset_bank()
        # reset_bank はアーカイブするだけなので明示的に初期状態へ
        ps._bank.update({"balance": ps.BANKROLL_START, "n": 0, "w": 0,
                         "l": 0, "t": 0, "pnl": 0.0})

    def tearDown(self):
        for p in (self._log.name,):
            if os.path.exists(p):
                os.unlink(p)
        ps.FORWARD_LOG = self._orig_log

    def test_win_loss_tie_math(self):
        s = ps.record_forward("win")            # +900 (1000 x 0.9)
        self.assertEqual(s["balance"], 5900)
        ps.record_forward("loss")               # -1000
        s = ps.record_forward("tie")            # +-0
        self.assertEqual(s["balance"], 4900)
        self.assertEqual((s["w"], s["l"], s["t"]), (1, 1, 1))
        self.assertEqual(s["win_rate"], 0.5)    # 同値は勝率の分母に入れない

    def test_stake_capped_by_balance(self):
        for _ in range(4):
            ps.record_forward("loss")
        s = ps.bank_snapshot()
        self.assertEqual(s["balance"], 1000)
        self.assertEqual(s["next_stake"], 1000)
        self.assertEqual(s["shots_left"], 1)
        ps.record_forward("loss")
        s = ps.bank_snapshot()
        self.assertEqual(s["balance"], 0)
        self.assertFalse(s["can_trade"])
        out = ps.record_forward("loss")
        self.assertIn("error", out)             # 残高0では記録できない

    def test_log_replay(self):
        ps.record_forward("win")
        ps.record_forward("loss")
        # 状態を消して復元
        ps._bank.update({"balance": ps.BANKROLL_START, "n": 0, "w": 0,
                         "l": 0, "t": 0, "pnl": 0.0})
        ps._replay_forward_log()
        s = ps.bank_snapshot()
        self.assertEqual(s["n"], 2)
        self.assertEqual(s["balance"], 4900)


class TestForwardSignal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json",
                                                mode="w")
        self._orig = ps.FORWARD_PATH
        ps.FORWARD_PATH = self._tmp.name
        ps._fwd_cache["mtime"] = None

    def tearDown(self):
        os.unlink(self._tmp.name)
        ps.FORWARD_PATH = self._orig
        ps._fwd_cache["mtime"] = None

    def _write(self, picks):
        json.dump({"mode": "forward_test", "picks": picks}, self._tmp)
        self._tmp.flush()

    def test_slot_gating_and_best_lcb(self):
        self._write([make_pick("CHFJPY", (17, 20), lcb=0.54),
                     make_pick("USDJPY", (17, 20), lcb=0.56),
                     make_pick("AUDJPY", (20, 24), lcb=0.57)])
        self._tmp.close()
        # 18時 → 17-20 の2本から LCB 最大の USDJPY
        sig = ps.forward_signal(now_jst_hour=18)
        self.assertEqual(sig["pick"]["pair"], "USDJPY")
        # 21時 → AUDJPY
        sig = ps.forward_signal(now_jst_hour=21)
        self.assertEqual(sig["pick"]["pair"], "AUDJPY")
        # 10時 → 時間帯外
        sig = ps.forward_signal(now_jst_hour=10)
        self.assertIsNone(sig["pick"])
        self.assertIn("時間帯外", sig["status"])


if __name__ == "__main__":
    unittest.main()
