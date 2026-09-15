"""ブローカー抽象と PaperBroker(仮想口座)。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.models import AccountState, Direction, Trade, TradeOutcome


@dataclass
class Order:
    """発注内容。バイナリーなので方向・掛け金・満期(足数)のみ。"""

    direction: Direction
    stake: float
    expiry_bars: int
    entry_price: float
    entry_time: int
    payout_rate: float = 0.85
    reason: str = ""


class Broker(ABC):
    """発注先の共通インタフェース。"""

    @abstractmethod
    def place(self, order: Order) -> Trade:
        """発注し、建玉(未決済 Trade)を返す。"""

    @abstractmethod
    def settle(self, trade: Trade, exit_price: float, settle_time: int) -> Trade:
        """満期価格で決済する。"""


class PaperBroker(Broker):
    """実弾を出さない仮想ブローカー。バックテスト/ペーパー共通の決済ロジック。"""

    def __init__(self, starting_balance: float = 1000.0):
        self.account = AccountState(balance=starting_balance)
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []

    def place(self, order: Order) -> Trade:
        if order.stake > self.account.balance:
            raise ValueError(
                f"残高不足: stake={order.stake} balance={self.account.balance}"
            )
        trade = Trade(
            entry_time=order.entry_time,
            direction=order.direction,
            entry_price=order.entry_price,
            expiry_bars=order.expiry_bars,
            stake=order.stake,
            payout_rate=order.payout_rate,
            reason=order.reason,
        )
        self.open_trades.append(trade)
        return trade

    def settle(self, trade: Trade, exit_price: float, settle_time: int) -> Trade:
        trade.settle(exit_price, settle_time)
        self.account.apply(trade)
        if trade in self.open_trades:
            self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        return trade

    @property
    def balance(self) -> float:
        return self.account.balance
