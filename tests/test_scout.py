"""通貨ペア・スカウト（オフライン経路）とスケジュールのテスト。

LLM 経路（Fable5→Opus4.8）はネットワーク・課金が絡むためユニットテストでは
呼ばない。ここでは「API が無くても決定論的に動き、正しいスキーマを返す」ことを検証する。
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.pair_stats import SlotStat, analyze_pair, rank_by_slot  # noqa: E402
from agents.schedule_schema import (  # noqa: E402
    build_schedule,
    current_slot,
    validate_schedule,
)
from agents.scout import run_scout  # noqa: E402

JST = timezone(timedelta(hours=9))


class TestPairStats(unittest.TestCase):
    def test_analyze_pair_returns_slots(self):
        res = analyze_pair("USDJPY", strategy="bollinger", expiry_min=3,
                           process="meanrevert", slots=[(20, 24), (0, 3)])
        self.assertIn((20, 24), res)
        for st in res.values():
            self.assertIsInstance(st, SlotStat)
            self.assertTrue(st.is_synthetic)  # 実データが無い環境

    def test_ranking_sorts_by_edge(self):
        # 手作りの統計でランキングの並びを検証
        analysis = {
            "A": {(20, 24): SlotStat("A", (20, 24), 0.55, 0.02, 500, 0.51, 0.59, 0.53, True, False)},
            "B": {(20, 24): SlotStat("B", (20, 24), 0.60, 0.07, 500, 0.56, 0.64, 0.53, True, False)},
        }
        ranking = rank_by_slot(analysis, [(20, 24)], min_trades=30)
        self.assertEqual(ranking[(20, 24)][0].pair, "B")  # edge の高い方が先頭


class TestSchedule(unittest.TestCase):
    def test_build_and_validate(self):
        analysis = {
            "EURJPY": {(20, 24): SlotStat("EURJPY", (20, 24), 0.56, 0.06, 1200, 0.53, 0.59, 0.53, True, False)},
            "USDJPY": {(20, 24): SlotStat("USDJPY", (20, 24), 0.50, 0.0, 1000, 0.47, 0.53, 0.53, False, False)},
        }
        ranking = rank_by_slot(analysis, [(20, 24)])
        sched = build_schedule(ranking, "bollinger", 3, 1.90, slots=[(20, 24)])
        self.assertEqual(validate_schedule(sched), [])
        slot0 = sched["slots"][0]
        self.assertEqual(slot0["recommended_pair"], "EURJPY")
        self.assertEqual(slot0["confidence"], "高")  # 有意 + サンプル>=1000

    def test_synthetic_confidence_label(self):
        analysis = {
            "EURJPY": {(20, 24): SlotStat("EURJPY", (20, 24), 0.56, 0.06, 1200, 0.53, 0.59, 0.53, True, True)},
        }
        ranking = rank_by_slot(analysis, [(20, 24)])
        sched = build_schedule(ranking, "bollinger", 3, 1.90, slots=[(20, 24)])
        self.assertEqual(sched["slots"][0]["confidence"], "デモ(合成データ)")

    def test_current_slot_lookup(self):
        analysis = {
            "EURJPY": {(20, 24): SlotStat("EURJPY", (20, 24), 0.56, 0.06, 1200, 0.53, 0.59, 0.53, True, False)},
        }
        ranking = rank_by_slot(analysis, [(20, 24)])
        sched = build_schedule(ranking, "bollinger", 3, 1.90, slots=[(20, 24)])
        now = datetime(2026, 7, 11, 21, 0, tzinfo=JST)  # JST 21時 -> 20-24 帯
        cur = current_slot(sched, now)
        self.assertIsNotNone(cur)
        self.assertEqual(cur["window"], "20:00-24:00")


class TestRunScoutOffline(unittest.TestCase):
    def test_offline_end_to_end(self):
        sched = run_scout(
            pairs=["USDJPY", "EURJPY"],
            strategy="bollinger",
            expiry_min=3,
            payout=1.90,
            process="meanrevert",
            slots=[(20, 24), (0, 3)],
            use_llm=False,
        )
        self.assertEqual(validate_schedule(sched), [])
        self.assertEqual(sched["mode"], "offline")
        self.assertEqual(len(sched["slots"]), 2)
        self.assertEqual(sched["orchestrator_model"], "claude-fable-5")
        self.assertEqual(sched["worker_model"], "claude-opus-4-8")


if __name__ == "__main__":
    unittest.main()
