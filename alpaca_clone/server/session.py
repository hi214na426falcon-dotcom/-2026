"""ペーパー運用セッション: 別スレッドで足を供給し続け、状態を保持する。

- source_candles を渡すとリプレイ、無ければ合成ランダムウォークを無限生成する。
- start()/stop() で制御。state()/events() で観測。
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

from ..core.models import Candle
from ..execution.broker import PaperBroker
from ..paper.trader import PaperTrader
from ..strategy.engine import StrategyConfig


class PaperSession:
    def __init__(
        self,
        config: StrategyConfig,
        stake: float = 10.0,
        stake_mode: str = "fixed",
        starting_balance: float = 1000.0,
        tick_interval: float = 1.0,
        seed: Optional[int] = 42,
        source_candles: Optional[List[Candle]] = None,
    ):
        self.config = config
        self.tick_interval = tick_interval
        self._events: Deque[dict] = deque(maxlen=300)

        self.trader = PaperTrader(
            config,
            broker=PaperBroker(starting_balance=starting_balance),
            stake=stake,
            stake_mode=stake_mode,
            on_event=self._record,
        )

        self._source = list(source_candles) if source_candles else None
        self._source_i = 0

        # 合成ライブ生成の状態
        self._rng = random.Random(seed)
        self._price = source_candles[-1].close if source_candles else 100.0
        self._time = source_candles[-1].timestamp if source_candles else 1_700_000_000
        self._interval_sec = 60

        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._lock = threading.Lock()

    # ---- 足の供給元 -------------------------------------------------
    def _next_candle(self) -> Optional[Candle]:
        if self._source is not None:
            if self._source_i >= len(self._source):
                return None  # リプレイ終了
            c = self._source[self._source_i]
            self._source_i += 1
            return c
        # 合成: 1 本生成
        o = self._price
        c = hi = lo = o
        for _ in range(4):
            c = max(0.01, c + self._rng.gauss(0.0, 0.4))
            hi = max(hi, c)
            lo = min(lo, c)
        self._price = c
        self._time += self._interval_sec
        return Candle(self._time, round(o, 4), round(hi, 4),
                      round(lo, 4), round(c, 4), 1000.0)

    # ---- スレッド制御 -----------------------------------------------
    def start(self) -> bool:
        if self._running.is_set():
            return False
        self._running.set()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._record({"kind": "start"})
        return True

    def stop(self) -> bool:
        if not self._running.is_set():
            return False
        self._running.clear()
        self._record({"kind": "stop"})
        return True

    def _loop(self) -> None:
        while self._running.is_set():
            candle = self._next_candle()
            if candle is None:
                self._running.clear()
                self._record({"kind": "exhausted"})
                break
            with self._lock:
                self.trader.feed_candle(candle)
            time.sleep(max(0.0, self.tick_interval))

    # ---- 観測 -------------------------------------------------------
    def _record(self, event: dict) -> None:
        event = dict(event)
        event["t"] = time.time()
        self._events.append(event)

    def state(self) -> Dict[str, object]:
        with self._lock:
            st = self.trader.state()
        st["running"] = self._running.is_set()
        st["tick_interval"] = self.tick_interval
        st["stake"] = self.trader.stake
        st["stake_mode"] = self.trader.stake_mode
        return st

    def events(self, limit: int = 50) -> List[dict]:
        return list(self._events)[-limit:]

    def set_stake(self, stake: float, mode: Optional[str] = None) -> None:
        with self._lock:
            self.trader.stake = float(stake)
            if mode in ("fixed", "percent"):
                self.trader.stake_mode = mode
