"""時間帯（JST セッション）分析。

MASTER_PROMPT のトレード時間帯は「夜 17〜24 時（ロンドン〜NY）＋深夜 0〜6 時」。
このモジュールは、バックテスト結果を **JST の時間帯ごと** に集計し、
「この時間帯はこの通貨ペア」を根拠づけるための材料を作る。

前提:
- バーの ``time`` は ISO8601 文字列。データ元（Dukascopy 等）は GMT が多いので、
  ``tz_offset_hours``（既定 9 = JST）でずらして時刻を解釈する。
- 先読みは一切しない（集計は確定済みトレードの時刻・結果のみを使う）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from .strategies import Signals

# MASTER_PROMPT の推奨時間帯（JST）。(開始時, 終了時) の半開区間の集合。
MASTER_SESSIONS_JST: List[Tuple[int, int]] = [(17, 24), (0, 6)]

# 表示用の時間帯ブロック（JST）。オーバーレイの「今の時間帯」判定に使う。
DEFAULT_SLOTS_JST: List[Tuple[int, int]] = [
    (17, 20),  # ロンドン序盤
    (20, 24),  # ロンドン〜NY 重複（最も動く）
    (0, 3),    # NY 後半
    (3, 6),    # NY クローズ前
]


def parse_hour(time_str: Optional[str], tz_offset_hours: int = 9) -> Optional[int]:
    """ISO 時刻文字列を JST（既定）の「時」(0-23) に変換する。

    解釈できない場合は None。epoch 秒／ミリ秒にも一応対応する。
    """
    if not time_str:
        return None
    s = str(time_str).strip()
    dt: Optional[datetime] = None
    # まず ISO8601 として解釈
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # tz 情報を捨てて素の時刻として扱い、オフセットを足す（保守的・単純）
        dt = dt.replace(tzinfo=None)
    except ValueError:
        # epoch 秒 / ミリ秒
        try:
            num = float(s)
            if num > 1e12:  # ミリ秒
                num /= 1000.0
            dt = datetime.utcfromtimestamp(num)
        except (ValueError, OverflowError, OSError):
            return None
    if dt is None:
        return None
    shifted = dt + timedelta(hours=tz_offset_hours)
    return shifted.hour


def hour_in_windows(hour: int, windows: Sequence[Tuple[int, int]]) -> bool:
    """時 (0-23) が (開始, 終了) 半開区間のいずれかに入るか。

    終了 > 24 や 開始 > 終了（日跨ぎ）にも対応する。
    """
    for start, end in windows:
        if start <= end:
            if start <= hour < end:
                return True
        else:  # 日跨ぎ（例: 22, 4）
            if hour >= start or hour < end:
                return True
    return False


def restrict_signals_to_sessions(
    times: Sequence[Optional[str]],
    signals: Signals,
    windows: Sequence[Tuple[int, int]] = tuple(MASTER_SESSIONS_JST),
    tz_offset_hours: int = 9,
) -> Signals:
    """指定 JST 時間帯の外側のシグナルを None にして無効化する。

    バックテスト時に「夜＋深夜だけで検証」するためのフィルタ。
    """
    out: Signals = []
    for t, sig in zip(times, signals):
        if sig is None:
            out.append(None)
            continue
        h = parse_hour(t, tz_offset_hours)
        out.append(sig if (h is not None and hour_in_windows(h, windows)) else None)
    return out


def _stats_from_counts(wins: int, losses: int, payout: float) -> Dict[str, float]:
    decided = wins + losses
    win_rate = wins / decided if decided else 0.0
    breakeven = 1.0 / payout
    if decided > 0:
        se = (win_rate * (1.0 - win_rate) / decided) ** 0.5
        ci_low = max(0.0, win_rate - 1.96 * se)
        ci_high = min(1.0, win_rate + 1.96 * se)
    else:
        ci_low = ci_high = 0.0
    return {
        "trades": float(decided),
        "wins": float(wins),
        "losses": float(losses),
        "win_rate": win_rate,
        "breakeven": breakeven,
        "edge": win_rate - breakeven,
        "ci_low": ci_low,
        "ci_high": ci_high,
        # 信頼区間の下限が損益分岐を上回る＝統計的にプラス側と言える
        "significant_plus": 1.0 if ci_low > breakeven else 0.0,
    }


def bucket_by_hour(
    trades,
    payout: float = 1.90,
    tz_offset_hours: int = 9,
) -> Dict[int, Dict[str, float]]:
    """確定トレード列を JST 時間 (0-23) ごとに集計する。

    trades: engine.Trade のリスト（time, result を持つ）。
    """
    wins: Dict[int, int] = {}
    losses: Dict[int, int] = {}
    for tr in trades:
        h = parse_hour(getattr(tr, "time", None), tz_offset_hours)
        if h is None:
            continue
        if tr.result == "win":
            wins[h] = wins.get(h, 0) + 1
        elif tr.result == "loss":
            losses[h] = losses.get(h, 0) + 1
    out: Dict[int, Dict[str, float]] = {}
    for h in range(24):
        w, l = wins.get(h, 0), losses.get(h, 0)
        if w + l == 0:
            continue
        out[h] = _stats_from_counts(w, l, payout)
    return out


def bucket_by_slot(
    trades,
    slots: Sequence[Tuple[int, int]] = tuple(DEFAULT_SLOTS_JST),
    payout: float = 1.90,
    tz_offset_hours: int = 9,
) -> Dict[Tuple[int, int], Dict[str, float]]:
    """確定トレード列を JST の時間帯ブロックごとに集計する。"""
    wins: Dict[Tuple[int, int], int] = {}
    losses: Dict[Tuple[int, int], int] = {}
    for tr in trades:
        h = parse_hour(getattr(tr, "time", None), tz_offset_hours)
        if h is None:
            continue
        for slot in slots:
            if hour_in_windows(h, [slot]):
                if tr.result == "win":
                    wins[slot] = wins.get(slot, 0) + 1
                elif tr.result == "loss":
                    losses[slot] = losses.get(slot, 0) + 1
                break
    out: Dict[Tuple[int, int], Dict[str, float]] = {}
    for slot in slots:
        w, l = wins.get(slot, 0), losses.get(slot, 0)
        out[slot] = _stats_from_counts(w, l, payout)
    return out


def slot_label(slot: Tuple[int, int]) -> str:
    """時間帯ブロックを "17:00-20:00" のような JST 表記にする。

    終端 24 は "24:00" のまま表示する（日本語の慣用: 24時＝深夜0時）。
    """
    start, end = slot
    end_disp = end if end == 24 else end % 24
    return f"{start:02d}:00-{end_disp:02d}:00"
