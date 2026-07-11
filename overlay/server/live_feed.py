"""相場フィード（直近1分足の供給）。

現在の推論に必要な「直近の終値列」を返す。優先順位:
1. ``data/m1/<PAIR>*.csv(.gz)`` のうち**最終更新が最新**のファイルの末尾
   （live_pull.py が追記する ``<PAIR>_live.csv`` が自然に最優先になる）。
2. 外部フィードが使えない場合もクラッシュせず None を返す（呼び出し側で待機表示）。
"""

from __future__ import annotations

import csv
import glob
import gzip
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
    """CSV(.gz) の末尾 n 本の (times, closes) を返す。読めなければ None。"""
    if not os.path.exists(path):
        return None
    times: List[Optional[str]] = []
    closes: List[float] = []
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", newline="", encoding="utf-8-sig") as f:
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
    return {"times": times, "closes": closes,
            "last_time": times[-1] if times else None}


def candidate_files(pair: str, data_dir: str) -> List[str]:
    """ペアに一致するデータファイルを最終更新の新しい順に返す。"""
    pats = [f"{pair}*.csv", f"{pair}*.csv.gz",
            f"{pair.lower()}*.csv", f"{pair.lower()}*.csv.gz"]
    found = []
    for pat in pats:
        found.extend(glob.glob(os.path.join(data_dir, pat)))
    return sorted(set(found), key=lambda p: os.path.getmtime(p), reverse=True)


def recent_bars(pair: str, data_dir: str, n: int = 400) -> Optional[Dict[str, list]]:
    """ペアの直近バーを取得（最新更新ファイル優先。live_pull の追記が最優先）。"""
    for path in candidate_files(pair, data_dir):
        got = recent_bars_from_csv(path, n)
        if got:
            got["source"] = os.path.basename(path)
            return got
    return None
