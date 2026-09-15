"""基本データ型。

バイナリーオプションを扱うので、ポジションは「価格の上下を当てる」だけの
単純なもの: CALL(上がる) / PUT(下がる) を予測し、満期(expiry)後の終値と
エントリー価格を比較して勝敗が決まる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    """売買方向。NONE はシグナル無し(何もしない)。"""

    CALL = "CALL"  # 満期時にエントリー価格より上と予測
    PUT = "PUT"    # 満期時にエントリー価格より下と予測
    NONE = "NONE"

    @property
    def opposite(self) -> "Direction":
        if self is Direction.CALL:
            return Direction.PUT
        if self is Direction.PUT:
            return Direction.CALL
        return Direction.NONE


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    TIE = "TIE"      # エントリー価格と満期価格が同値(引き分け=返金)
    PENDING = "PENDING"


@dataclass(frozen=True)
class Candle:
    """1本のローソク足(OHLCV)。timestamp は UNIX 秒。"""

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_row(cls, row: dict) -> "Candle":
        """CSV 等の 1 行(dict)から生成。列名は緩く受け付ける。"""

        def g(*keys: str, default: Optional[float] = None):
            for k in keys:
                if k in row and row[k] not in ("", None):
                    return row[k]
            if default is not None:
                return default
            raise KeyError(f"必要な列が見つかりません: {keys}")

        ts_raw = g("timestamp", "time", "date", "datetime")
        return cls(
            timestamp=_to_epoch(ts_raw),
            open=float(g("open", "o")),
            high=float(g("high", "h")),
            low=float(g("low", "l")),
            close=float(g("close", "c")),
            volume=float(g("volume", "v", default=0.0)),
        )


@dataclass(frozen=True)
class Signal:
    """エンジンが出す判断。direction が NONE 以外なら発注候補。"""

    timestamp: int
    direction: Direction
    expiry_bars: int
    reason: str = ""
    confidence: float = 1.0

    @property
    def is_trade(self) -> bool:
        return self.direction is not Direction.NONE


@dataclass
class Trade:
    """1 回の取引(発注〜決済)。"""

    entry_time: int
    direction: Direction
    entry_price: float
    expiry_bars: int
    stake: float
    payout_rate: float
    settle_time: Optional[int] = None
    exit_price: Optional[float] = None
    outcome: TradeOutcome = TradeOutcome.PENDING
    pnl: float = 0.0
    reason: str = ""

    def settle(self, exit_price: float, settle_time: int) -> None:
        """満期価格で決済し、勝敗と損益を確定する。"""
        self.exit_price = exit_price
        self.settle_time = settle_time
        if self.direction is Direction.CALL:
            won = exit_price > self.entry_price
        elif self.direction is Direction.PUT:
            won = exit_price < self.entry_price
        else:
            won = False

        if exit_price == self.entry_price:
            self.outcome = TradeOutcome.TIE
            self.pnl = 0.0
        elif won:
            self.outcome = TradeOutcome.WIN
            self.pnl = self.stake * self.payout_rate
        else:
            self.outcome = TradeOutcome.LOSS
            self.pnl = -self.stake


@dataclass
class AccountState:
    """仮想口座の状態。"""

    balance: float
    starting_balance: float = field(init=False)
    wins: int = 0
    losses: int = 0
    ties: int = 0

    def __post_init__(self) -> None:
        self.starting_balance = self.balance

    def apply(self, trade: Trade) -> None:
        self.balance += trade.pnl
        if trade.outcome is TradeOutcome.WIN:
            self.wins += 1
        elif trade.outcome is TradeOutcome.LOSS:
            self.losses += 1
        elif trade.outcome is TradeOutcome.TIE:
            self.ties += 1

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return self.wins / decided if decided else 0.0


def _to_epoch(value) -> int:
    """様々な時刻表現を UNIX 秒(int)へ変換する。"""
    import datetime as _dt

    if isinstance(value, (int, float)):
        v = float(value)
        # ミリ秒っぽい大きな値は秒へ
        return int(v / 1000) if v > 1e12 else int(v)
    s = str(value).strip()
    if s.isdigit():
        v = float(s)
        return int(v / 1000) if v > 1e12 else int(v)
    # ISO 8601 を試す
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = _dt.datetime.strptime(s, fmt).replace(tzinfo=_dt.timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    # 最後に fromisoformat
    try:
        dt = _dt.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return int(dt.timestamp())
    except ValueError as exc:  # pragma: no cover - 想定外フォーマット
        raise ValueError(f"時刻を解釈できません: {value!r}") from exc
