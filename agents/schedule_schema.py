"""time→pair スケジュールのスキーマ・生成・検証・現在スロット判定。

``schedule.json`` は「どの時間帯にどのペアを、どれくらいの勝率で狙うか」を
表す唯一の連携ファイル。scout が生成し、predict_server 経由でオーバーレイが読む。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from backtest.sessions import DEFAULT_SLOTS_JST, hour_in_windows, slot_label

SCHEMA_VERSION = 1

JST = timezone(timedelta(hours=9))

DISCLAIMER = (
    "この推奨はバックテスト統計に基づく参考情報です。実弾投入前にデモでの"
    "フォワードテストが必須。勝率は損益分岐（=1/ペイアウト）を安定して上回る"
    "場合のみ意味を持ちます。合成データ由来（is_synthetic=true）の数字は"
    "実運用の根拠になりません。"
)


def _confidence(trades: int, significant_plus: bool, is_synthetic: bool) -> str:
    """サンプル数・有意性・データ種別から信頼度ラベルを決める。"""
    if is_synthetic:
        return "デモ(合成データ)"
    if trades < 200:
        return "低(サンプル不足)"
    if significant_plus and trades >= 1000:
        return "高"
    if significant_plus:
        return "中"
    return "低(有意でない)"


def build_slot_entry(slot: Tuple[int, int], ranked_rows, worker_notes=None) -> Dict:
    """1 時間帯ぶんのスケジュール項目を作る。

    ranked_rows: エッジ降順に並んだ SlotStat のリスト（pair_stats.rank_by_slot の出力）。
    worker_notes: {pair: {"rationale":..., "confidence":..., "go": bool}} 任意（LLM 経路）。
    """
    ranking = [
        {
            "pair": s.pair,
            "win_rate": round(s.win_rate, 4),
            "edge_pt": round(s.edge * 100, 2),
            "trades": s.trades,
            "ci_low": round(s.ci_low, 4),
            "ci_high": round(s.ci_high, 4),
            "significant_plus": s.significant_plus,
            "is_synthetic": s.is_synthetic,
        }
        for s in ranked_rows
    ]
    top = ranked_rows[0] if ranked_rows else None
    entry: Dict = {
        "window": slot_label(slot),
        "hours": list(range(slot[0], slot[1])) if slot[0] <= slot[1] else
                 list(range(slot[0], 24)) + list(range(0, slot[1])),
        "recommended_pair": top.pair if top else None,
        "expected_win_rate": round(top.win_rate, 4) if top else None,
        "edge_pt": round(top.edge * 100, 2) if top else None,
        "sample": top.trades if top else 0,
        "ci_low": round(top.ci_low, 4) if top else None,
        "ci_high": round(top.ci_high, 4) if top else None,
        "confidence": _confidence(top.trades, top.significant_plus, top.is_synthetic)
        if top else "データなし",
        "ranking": ranking,
        "rationale": "",
    }
    if worker_notes and top and top.pair in worker_notes:
        note = worker_notes[top.pair]
        entry["rationale"] = note.get("rationale", "")
        if "confidence" in note:
            entry["worker_confidence"] = note["confidence"]
        entry["go"] = bool(note.get("go", top.significant_plus))
    else:
        # 決定論(オフライン)経路の定型根拠
        if top and top.significant_plus:
            entry["rationale"] = (
                f"{slot_label(slot)}(JST) は {top.pair} の損益分岐超えが"
                f"統計的に確認された時間帯（サンプル {top.trades}件）。"
            )
        elif top:
            entry["rationale"] = (
                f"{slot_label(slot)}(JST) は明確なエッジが未確認。"
                "参考順位のみ、実弾は見送り推奨。"
            )
        entry["go"] = bool(top.significant_plus) if top else False
    return entry


def build_schedule(
    ranking: Dict[Tuple[int, int], list],
    strategy: str,
    expiry_min: int,
    payout: float,
    mode: str = "offline",
    orchestrator_model: str = "claude-fable-5",
    worker_model: str = "claude-opus-4-8",
    worker_notes: Optional[Dict[Tuple[int, int], dict]] = None,
    slots: Sequence[Tuple[int, int]] = tuple(DEFAULT_SLOTS_JST),
) -> Dict:
    """スケジュール全体（配信用 dict）を組み立てる。"""
    entries = []
    for slot in slots:
        rows = ranking.get(slot, [])
        notes = (worker_notes or {}).get(slot)
        entries.append(build_slot_entry(slot, rows, notes))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tz": "JST",
        "mode": mode,  # "offline" | "llm"
        "orchestrator_model": orchestrator_model,
        "worker_model": worker_model,
        "strategy": {"name": strategy, "expiry_min": expiry_min, "payout": payout},
        "slots": entries,
        "disclaimer": DISCLAIMER,
    }


def validate_schedule(sched: Dict) -> List[str]:
    """スケジュールの最低限の健全性を検査し、問題点の一覧を返す（空なら OK）。"""
    problems: List[str] = []
    if not isinstance(sched, dict):
        return ["スケジュールが dict ではありません"]
    if sched.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version が一致しません")
    for key in ("generated_at", "strategy", "slots"):
        if key not in sched:
            problems.append(f"必須キー欠落: {key}")
    for i, slot in enumerate(sched.get("slots", [])):
        if "window" not in slot:
            problems.append(f"slots[{i}] に window がありません")
        wr = slot.get("expected_win_rate")
        if wr is not None and not (0.0 <= wr <= 1.0):
            problems.append(f"slots[{i}] の expected_win_rate が範囲外: {wr}")
    return problems


def current_slot(sched: Dict, now: Optional[datetime] = None) -> Optional[Dict]:
    """現在の JST 時刻に該当するスロットを返す（無ければ None）。"""
    if now is None:
        now = datetime.now(JST)
    elif now.tzinfo is not None:
        now = now.astimezone(JST)
    hour = now.hour
    for slot in sched.get("slots", []):
        hours = slot.get("hours") or []
        if hour in hours:
            return slot
    return None
