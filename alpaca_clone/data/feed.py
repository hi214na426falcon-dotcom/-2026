"""ローソク足フィード。

- CSVFeed:      ヒストリカルCSVを読む(バックテスト用)。
- SyntheticFeed: ランダムウォークで足を生成(依存無しでの動作確認/テスト用)。

いずれも「確定した足」を time 昇順で列挙する。バイナリーの検証は確定足ベース。
"""

from __future__ import annotations

import csv
import math
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, List, Optional, Union

from ..core.models import Candle


class CandleFeed(ABC):
    """ローソク足の供給元。"""

    @abstractmethod
    def candles(self) -> List[Candle]:
        """time 昇順の確定足リストを返す。"""
        raise NotImplementedError


def load_candles_csv(path: Union[str, Path]) -> List[Candle]:
    """OHLCV CSV を読み込む。ヘッダ名は緩く受け付ける(time/timestamp/date 等)。"""
    rows: List[Candle] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV にヘッダがありません")
        # ヘッダを小文字化して受け付ける
        norm = {name: (name.strip().lower()) for name in reader.fieldnames}
        for raw in reader:
            row = {norm[k]: v for k, v in raw.items() if k is not None}
            rows.append(Candle.from_row(row))
    rows.sort(key=lambda c: c.timestamp)
    return rows


class CSVFeed(CandleFeed):
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._candles: Optional[List[Candle]] = None

    def candles(self) -> List[Candle]:
        if self._candles is None:
            self._candles = load_candles_csv(self.path)
        return self._candles


class SyntheticFeed(CandleFeed):
    """再現可能なランダムウォークで OHLCV を生成する。

    実データの代わりにロジック検証・デモに使う(相場予測の意味は無い)。
    """

    def __init__(
        self,
        n: int = 500,
        start_price: float = 100.0,
        volatility: float = 0.4,
        seed: Optional[int] = 42,
        interval_sec: int = 60,
        start_time: int = 1_700_000_000,
        drift: float = 0.0,
    ):
        self.n = n
        self.start_price = start_price
        self.volatility = volatility
        self.seed = seed
        self.interval_sec = interval_sec
        self.start_time = start_time
        self.drift = drift

    def candles(self) -> List[Candle]:
        rng = random.Random(self.seed)
        out: List[Candle] = []
        price = self.start_price
        t = self.start_time
        for _ in range(self.n):
            o = price
            # 足内で数ステップ動かして高値/安値を作る
            hi = lo = c = o
            steps = 4
            for _ in range(steps):
                shock = rng.gauss(self.drift, self.volatility)
                c = max(0.01, c + shock)
                hi = max(hi, c)
                lo = min(lo, c)
            vol = abs(rng.gauss(1000, 200))
            out.append(Candle(timestamp=t, open=round(o, 4), high=round(hi, 4),
                              low=round(lo, 4), close=round(c, 4), volume=round(vol, 2)))
            price = c
            t += self.interval_sec
        return out

    def stream(self) -> Iterator[Candle]:
        """ペーパートレードのライブ模擬用に 1 本ずつ返す。"""
        yield from self.candles()


def cyclical_feed(
    n: int = 500,
    base: float = 100.0,
    amplitude: float = 5.0,
    period_bars: int = 40,
    noise: float = 0.2,
    seed: Optional[int] = 7,
    interval_sec: int = 60,
    start_time: int = 1_700_000_000,
) -> List[Candle]:
    """サイン波+ノイズの循環的な系列。反転系ロジックのテストに使える。"""
    rng = random.Random(seed)
    out: List[Candle] = []
    t = start_time
    prev_close = base
    for i in range(n):
        center = base + amplitude * math.sin(2 * math.pi * i / period_bars)
        o = prev_close
        c = center + rng.gauss(0, noise)
        hi = max(o, c) + abs(rng.gauss(0, noise))
        lo = min(o, c) - abs(rng.gauss(0, noise))
        out.append(Candle(timestamp=t, open=round(o, 4), high=round(hi, 4),
                          low=round(lo, 4), close=round(c, 4), volume=1000.0))
        prev_close = c
        t += interval_sec
    return out
