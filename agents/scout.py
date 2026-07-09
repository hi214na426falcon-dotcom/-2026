"""通貨ペア・スカウト（マルチエージェント本体）。

構成:
- **オーケストレーター = Claude Fable 5**（``claude-fable-5``）
  バックテスト統計を俯瞰し、各時間帯で「どのペアを精査すべきか」を決めて
  下位ワーカーに指示を出す（＝計画・判断の頭脳。呼び出し回数は 1 回に抑える）。
- **ワーカー = Claude Opus 4.8**（``claude-opus-4-8``）
  指示された 1 時間帯だけを担当し、数字を読んで「推奨ペア・根拠・GO/見送り」を
  返す。安価なモデルに実作業を寄せることでコストパフォーマンスを出す。

安全策:
- ``anthropic`` SDK が無い／API 鍵が無い／通信に失敗した場合は、例外を投げずに
  **決定論的な統計計算（オフライン経路）へ自動フォールバック**する。
- LLM はあくまで「数字への説明づけ」。勝率の数値は pair_stats（実測）由来で、
  モデルが創作することはない。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Sequence, Tuple

from backtest.sessions import DEFAULT_SLOTS_JST, MASTER_SESSIONS_JST, slot_label
from .pair_stats import DEFAULT_PAIRS, analyze_pairs, rank_by_slot
from .schedule_schema import build_schedule

ORCHESTRATOR_MODEL = "claude-fable-5"
WORKER_MODEL = "claude-opus-4-8"


# --- LLM 経路のヘルパー -------------------------------------------------------

def _client():
    """anthropic クライアントを返す（未導入なら None）。"""
    try:
        import anthropic  # 遅延 import（未導入でもオフライン経路は動く）
    except Exception:
        return None
    try:
        return anthropic.Anthropic()
    except Exception:
        return None


def _summarize_ranking(ranking: Dict[Tuple[int, int], list], top_n: int = 4) -> List[Dict]:
    """LLM に渡す用のコンパクトな要約（各時間帯の上位候補）。"""
    out = []
    for slot, rows in ranking.items():
        out.append({
            "window": slot_label(slot),
            "candidates": [
                {
                    "pair": s.pair,
                    "win_rate": round(s.win_rate, 4),
                    "edge_pt": round(s.edge * 100, 2),
                    "trades": s.trades,
                    "significant_plus": s.significant_plus,
                    "is_synthetic": s.is_synthetic,
                }
                for s in rows[:top_n]
            ],
        })
    return out


def _first_json(resp) -> Optional[dict]:
    """レスポンスの最初の text ブロックを JSON として読む（失敗時 None）。"""
    try:
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return json.loads(block.text)
    except Exception:
        return None
    return None


def _orchestrate(client, summary: List[Dict]) -> Optional[List[Dict]]:
    """Fable 5 に調査計画（各時間帯の担当ペアと指示）を立てさせる。"""
    schema = {
        "type": "object",
        "properties": {
            "plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "window": {"type": "string"},
                        "focus_pair": {"type": "string"},
                        "instruction": {"type": "string"},
                    },
                    "required": ["window", "focus_pair", "instruction"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["plan"],
        "additionalProperties": False,
    }
    system = (
        "あなたはバイナリーオプションのクオンツ・オーケストレーターです。"
        "各時間帯(JST)の候補ペアの統計(勝率・損益分岐との差edge_pt・サンプル数trades・"
        "統計的有意significant_plus・合成データか is_synthetic)を見て、"
        "各時間帯で最も有望なペア(focus_pair)を1つ選び、"
        "担当ワーカーへの短い調査指示(instruction, 日本語)を書いてください。"
        "サンプル不足や合成データは慎重に。数値は創作しないこと。JSONのみ出力。"
    )
    user = "各時間帯の候補統計:\n" + json.dumps(summary, ensure_ascii=False)
    resp = client.beta.messages.create(
        model=ORCHESTRATOR_MODEL,
        max_tokens=4096,
        betas=["server-side-fallback-2026-06-01"],
        fallbacks=[{"model": WORKER_MODEL}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        return None
    data = _first_json(resp)
    return data.get("plan") if isinstance(data, dict) else None


def _worker(client, window: str, instruction: str, candidates: List[Dict]) -> Optional[Dict]:
    """Opus 4.8 ワーカーに 1 時間帯を精査させ、推奨と根拠を書かせる。"""
    schema = {
        "type": "object",
        "properties": {
            "pair": {"type": "string"},
            "go": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["高", "中", "低"]},
            "rationale": {"type": "string"},
        },
        "required": ["pair", "go", "confidence", "rationale"],
        "additionalProperties": False,
    }
    system = (
        "あなたはバイナリーオプションの分析ワーカーです。指定された時間帯(JST)の"
        "候補ペア統計だけを見て、推奨ペア(pair)・実弾GO可否(go)・信頼度(confidence)・"
        "根拠(rationale, 日本語1〜2文)を返します。損益分岐を統計的に超えていなければ"
        "go=false。合成データ(is_synthetic=true)は必ずgo=false。数値は創作しない。JSONのみ。"
    )
    user = (
        f"時間帯: {window}(JST)\nオーケストレーターの指示: {instruction}\n"
        f"候補統計: {json.dumps(candidates, ensure_ascii=False)}"
    )
    resp = client.messages.create(
        model=WORKER_MODEL,
        max_tokens=1024,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _first_json(resp)


# --- 公開 API ----------------------------------------------------------------

def run_scout(
    pairs: Sequence[str] = tuple(DEFAULT_PAIRS),
    strategy: str = "bollinger",
    strategy_kwargs: Optional[dict] = None,
    expiry_min: int = 3,
    payout: float = 1.90,
    slots: Sequence[Tuple[int, int]] = tuple(DEFAULT_SLOTS_JST),
    sessions: Sequence[Tuple[int, int]] = tuple(MASTER_SESSIONS_JST),
    data_dir: str = "data/m1",
    process: str = "randomwalk",
    use_llm: bool = True,
    min_trades: int = 30,
) -> Dict:
    """スカウトを実行して schedule(dict) を返す。

    use_llm=True かつ API 鍵があれば Fable5→Opus4.8 のマルチエージェント経路、
    そうでなければ決定論的なオフライン経路。どちらでも同じスキーマを返す。
    """
    # 1) 事実の土台（実測統計）
    analysis = analyze_pairs(
        pairs,
        strategy=strategy,
        strategy_kwargs=strategy_kwargs,
        expiry_min=expiry_min,
        payout=payout,
        slots=slots,
        sessions=sessions,
        data_dir=data_dir,
        process=process,
    )
    ranking = rank_by_slot(analysis, slots, min_trades=min_trades)

    # 2) LLM 経路（可能なら）
    worker_notes: Dict[Tuple[int, int], dict] = {}
    mode = "offline"
    if use_llm:
        client = _client()
        if client is not None:
            try:
                summary = _summarize_ranking(ranking)
                plan = _orchestrate(client, summary) or []
                plan_by_window = {p.get("window"): p for p in plan}
                any_worker = False
                for slot in slots:
                    label = slot_label(slot)
                    p = plan_by_window.get(label)
                    cands = next(
                        (s["candidates"] for s in summary if s["window"] == label), []
                    )
                    instruction = p.get("instruction", "最有望ペアを精査してください") if p else ""
                    note = _worker(client, label, instruction, cands)
                    if isinstance(note, dict) and note.get("pair"):
                        worker_notes[slot] = note
                        any_worker = True
                if any_worker:
                    mode = "llm"
            except Exception:
                # 通信・認証・その他いかなる失敗もオフラインへ退避
                worker_notes = {}
                mode = "offline"

    # 3) スケジュール組み立て
    sched = build_schedule(
        ranking,
        strategy=strategy,
        expiry_min=expiry_min,
        payout=payout,
        mode=mode,
        orchestrator_model=ORCHESTRATOR_MODEL,
        worker_model=WORKER_MODEL,
        worker_notes=worker_notes if mode == "llm" else None,
        slots=slots,
    )
    return sched
