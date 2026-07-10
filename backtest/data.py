"""価格データの生成・読み込み（標準ライブラリのみ）。

- ``Series`` は OHLC バー列のコンテナ。
- ``load_csv`` は実データ（MT4/MT5 エクスポート, Dukascopy, 各種 API の CSV 等）を読み込む。
- ``generate_synthetic`` はデモ・検証用に合成価格を生成する。

【正直な注意】
合成データは「戦略が必ず勝てるように」恣意的に作っていない。既定はドリフトの
ない対数ランダムウォーク（= 本質的に優位性が生じない）であり、ほとんどの戦略は
勝率 50% 近辺に落ち着く。これは現実の「為替は予測が難しい」という性質を反映した
意図的な設計である。``process="meanrevert"`` 等にすると逆張り系にわずかな優位が
出るが、それでも 80% には到達しない。
"""

from __future__ import annotations

import csv
import gzip
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class Bar:
    """1 本のローソク足。time は表示用の文字列（None 可）。"""

    time: Optional[str]
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Series:
    bars: List[Bar] = field(default_factory=list)
    name: str = "series"

    @property
    def closes(self) -> List[float]:
        return [b.close for b in self.bars]

    def __len__(self) -> int:
        return len(self.bars)

    def slice(self, start: int, end: Optional[int] = None) -> "Series":
        return Series(self.bars[start:end], name=f"{self.name}[{start}:{end}]")


# --- CSV 読み込み -----------------------------------------------------------

_TIME_KEYS = ("time", "timestamp", "date", "datetime", "<date>", "gmt time")
_OPEN_KEYS = ("open", "o", "<open>")
_HIGH_KEYS = ("high", "h", "<high>")
_LOW_KEYS = ("low", "l", "<low>")
_CLOSE_KEYS = ("close", "c", "price", "<close>")
_VOL_KEYS = ("volume", "vol", "v", "<vol>", "<volume>")


def _find_key(fieldnames: List[str], candidates) -> Optional[str]:
    lower = {f.lower().strip(): f for f in fieldnames if f is not None}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def load_csv(path: str, name: Optional[str] = None) -> Series:
    """OHLC の CSV を読み込む。

    ヘッダー名は大文字小文字を無視して柔軟に判定する。最低限 close（または price）
    列が必要。open/high/low が無い場合は close で代用する。
    """
    bars: List[Bar] = []
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fns = reader.fieldnames or []
        kt = _find_key(fns, _TIME_KEYS)
        ko = _find_key(fns, _OPEN_KEYS)
        kh = _find_key(fns, _HIGH_KEYS)
        kl = _find_key(fns, _LOW_KEYS)
        kc = _find_key(fns, _CLOSE_KEYS)
        kv = _find_key(fns, _VOL_KEYS)
        if kc is None:
            raise ValueError(
                f"CSV に close（または price）列が見つかりません。検出ヘッダー: {fns}"
            )
        for row in reader:
            try:
                close = float(row[kc])
            except (TypeError, ValueError):
                continue  # 空行・壊れた行はスキップ
            o = float(row[ko]) if ko and row.get(ko) not in (None, "") else close
            h = float(row[kh]) if kh and row.get(kh) not in (None, "") else max(o, close)
            l = float(row[kl]) if kl and row.get(kl) not in (None, "") else min(o, close)
            v = 0.0
            if kv and row.get(kv) not in (None, ""):
                try:
                    v = float(row[kv])
                except ValueError:
                    v = 0.0
            t = row.get(kt) if kt else None
            bars.append(Bar(time=t, open=o, high=h, low=l, close=close, volume=v))
    if not bars:
        raise ValueError("読み込めるデータ行がありませんでした。")
    return Series(bars, name=name or path)


# --- 合成データ生成 ---------------------------------------------------------


def generate_synthetic(
    n: int = 3000,
    start_price: float = 150.0,
    seed: int = 42,
    process: str = "randomwalk",  # "randomwalk" | "meanrevert" | "trend"
    drift: float = 0.0,
    vol: float = 0.0008,
    mean_revert_strength: float = 0.02,
    bar_minutes: int = 5,
    start_time: str = "2024-01-01T00:00:00",
) -> Series:
    """合成 OHLC を生成する。

    対数価格に対して、ショック(正規乱数)・ドリフト・平均回帰を適用する。
    - randomwalk : 優位性なし（既定）。勝率は理論上 50% に収束。
    - meanrevert : 直近水準へ引き戻す力。逆張り系がわずかに有利。
    - trend      : 一定ドリフト。順張り系が有利（ただし将来のドリフト方向を
                   事前に知ることは現実にはできない、という点に注意）。
    """
    rng = random.Random(seed)
    log_level = math.log(start_price)
    mean_level = log_level
    closes: List[float] = [start_price]
    for _ in range(1, n):
        shock = rng.gauss(0.0, vol)
        if process == "meanrevert":
            log_level += mean_revert_strength * (mean_level - log_level) + shock
        elif process == "trend":
            log_level += drift + shock
        else:  # randomwalk
            log_level += drift + shock
        closes.append(math.exp(log_level))

    try:
        t0 = datetime.fromisoformat(start_time)
    except ValueError:
        t0 = datetime(2024, 1, 1)

    bars: List[Bar] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        wick = abs(rng.gauss(0.0, vol)) * 0.5
        hi = max(o, c) * (1.0 + wick)
        lo = min(o, c) * (1.0 - wick)
        ts = (t0 + timedelta(minutes=bar_minutes * i)).isoformat()
        bars.append(Bar(time=ts, open=o, high=hi, low=lo, close=c))
    return Series(bars, name=f"synthetic-{process}")
