"""相場フィード（直近1分足の供給）。

現在の推論に必要な「直近の終値列」を返す。優先順位:
1. ``data/m1/<PAIR>.csv`` の末尾（オフラインでも動く。fetch_dukascopy.py で用意）。
2. （将来）ライブAPI。※この環境では外部エグレスが塞がれているため未接続。

外部フィードが使えない場合もクラッシュせず None を返す（呼び出し側で待機表示）。
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional

_TIME_KEYS = ("time", "timestamp", "date", "datetime", "gmt time")
_CLOSE_KEYS = ("close", "c", "price")


def _find(fieldnames, cands):
    low = {f.lower().strip(): f for f in (fieldnames or []) if f}
    for c in cands:
        if c in low:
            return low[c]
    return None


def recent_bars_from_csv(path: str, n: int = 400) -> Optional[Dict[str, list]]:
    """CSV の末尾 n 本の (times, closes) を返す。読めなければ None。"""
    if not os.path.exists(path):
        return None
    times: List[Optional[str]] = []
    closes: List[float] = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            kt = _find(reader.fieldnames, _TIME_KEYS)
            kc = _find(reader.fieldnames, _CLOSE_KEYS)
            if kc is None:
                return None
            for row in reader:
                try:
                    closes.append(float(row[kc]))
                except (TypeError, ValueError):
                    continue
                times.append(row.get(kt) if kt else None)
    except OSError:
        return None
    if not closes:
        return None
    times, closes = times[-n:], closes[-n:]
    return {"times": times, "closes": closes, "last_time": times[-1] if times else None}


def recent_bars(pair: str, data_dir: str, n: int = 400) -> Optional[Dict[str, list]]:
    """ペアの直近バーを取得（現状は data_dir の CSV から）。"""
    for name in (f"{pair}.csv", f"{pair}_M1.csv", f"{pair.lower()}.csv"):
        path = os.path.join(data_dir, name)
        got = recent_bars_from_csv(path, n)
        if got:
            got["source"] = os.path.basename(path)
            return got
    return None
