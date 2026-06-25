"""ブローカー接続層.

重要 (安全と法令順守):
  * 実ブローカーへの自動発注 (LiveBroker) は *意図的に未実装* です。
  * 海外バイナリ業者の多くは自動売買・スキャルピングを規約で禁止しており、
    違反は口座凍結・利益没収の対象。さらに無登録業者の日本居住者向け営業は
    金商法違反です。実弾接続を行うかは利用者の責任であり、ここでは雛形のみ
    提供します (資格情報も発注処理も持ちません)。
  * デフォルトで動くのは DemoBroker (完全シミュレーション) だけです。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from .strategy import UP, DOWN


@dataclass
class Order:
    entry_idx: int
    entry_time: object
    entry_price: float
    direction: int           # UP / DOWN
    stake: float
    horizon: int
    settle_idx: int
    exit_time: object = None
    exit_price: float = None
    outcome: str = None       # win/loss/push
    pnl: float = None


class BrokerConnector:
    """抽象インターフェース. 実装は最低限これらを満たすこと."""

    name: str = "abstract"

    def visible(self, lookback: Optional[int] = None) -> pd.DataFrame:
        raise NotImplementedError

    def get_balance(self) -> float:
        raise NotImplementedError

    def place_binary_order(self, direction: int, stake: float, horizon: int) -> Order:
        raise NotImplementedError

    def step(self) -> bool:
        """1バー進める. まだ続けられれば True."""
        raise NotImplementedError

    def has_open_position(self) -> bool:
        raise NotImplementedError


class DemoBroker(BrokerConnector):
    """完全シミュレーションのブローカー.

    既知の価格系列 prices を内部に持ち、cursor 位置までしか visible() で見せない
    (= 未来を覗かない)。発注は cursor 時点の close で約定し、horizon バー後に判定。
    """

    name = "demo"

    def __init__(self, prices: pd.DataFrame, balance: float = 100_000.0,
                 payout: float = 0.85, tie: str = "loss", one_position: bool = True):
        self.prices = prices.reset_index().rename(columns={"index": "time"})
        if "time" not in self.prices.columns:
            self.prices.insert(0, "time", prices.index)
        self._close = prices["close"].to_numpy(dtype=float)
        self._time = prices.index.to_numpy()
        self.cursor = 0
        self.start_balance = float(balance)
        self.balance = float(balance)
        self.payout = float(payout)
        self.tie = tie
        self.one_position = one_position
        self.open_orders: List[Order] = []
        self.history: List[Order] = []

    # --- 市場の見え方 ------------------------------------------------------
    def visible(self, lookback: Optional[int] = None) -> pd.DataFrame:
        hi = self.cursor + 1
        lo = 0 if lookback is None else max(0, hi - lookback)
        df = self.prices.iloc[lo:hi].copy()
        return df.set_index("time")[["open", "high", "low", "close"]]

    def get_balance(self) -> float:
        return self.balance

    def has_open_position(self) -> bool:
        return len(self.open_orders) > 0

    # --- 発注 --------------------------------------------------------------
    def place_binary_order(self, direction: int, stake: float, horizon: int) -> Order:
        if self.one_position and self.has_open_position():
            raise RuntimeError("既に建玉あり (one_position=True)")
        idx = self.cursor
        order = Order(
            entry_idx=idx, entry_time=self._time[idx],
            entry_price=float(self._close[idx]), direction=direction,
            stake=float(stake), horizon=horizon, settle_idx=idx + horizon,
        )
        self.open_orders.append(order)
        return order

    # --- 時間を進める / 決済 ----------------------------------------------
    def step(self) -> bool:
        if self.cursor >= len(self._close) - 1:
            return False
        self.cursor += 1
        self._settle_due()
        return True

    def _settle_due(self) -> None:
        still_open = []
        for o in self.open_orders:
            if self.cursor >= o.settle_idx:
                self._settle(o)
            else:
                still_open.append(o)
        self.open_orders = still_open

    def _settle(self, o: Order) -> None:
        exit_p = float(self._close[o.settle_idx])
        diff = exit_p - o.entry_price
        if diff == 0.0:
            outcome = {"loss": "loss", "push": "push", "win": "win"}[self.tie]
        elif (diff > 0 and o.direction == UP) or (diff < 0 and o.direction == DOWN):
            outcome = "win"
        else:
            outcome = "loss"
        pnl = o.stake * self.payout if outcome == "win" else (0.0 if outcome == "push" else -o.stake)
        o.exit_time = self._time[o.settle_idx]
        o.exit_price = exit_p
        o.outcome = outcome
        o.pnl = pnl
        self.balance += pnl
        self.history.append(o)

    def finalize(self) -> None:
        """残った建玉を最終バーで強制決済."""
        last = len(self._close) - 1
        for o in list(self.open_orders):
            o.settle_idx = min(o.settle_idx, last)
            self._settle(o)
        self.open_orders = []

    def trades_df(self) -> pd.DataFrame:
        rows = [{
            "entry_time": o.entry_time, "exit_time": o.exit_time,
            "direction": "UP" if o.direction == UP else "DOWN",
            "entry_price": o.entry_price, "exit_price": o.exit_price,
            "outcome": o.outcome, "pnl": o.pnl,
        } for o in self.history]
        cols = ["entry_time", "exit_time", "direction", "entry_price",
                "exit_price", "outcome", "pnl"]
        return pd.DataFrame(rows, columns=cols)


class LiveBroker(BrokerConnector):
    """実ブローカー接続の *雛形*. 意図的に未実装。

    実装するなら利用者自身が、対象業者のAPI・規約・各国法令を確認した上で
    self-責任で行うこと。binbot はここに資格情報も発注ロジックも持たない。
    """

    name = "live(disabled)"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "LiveBroker は安全のため未実装です。実弾の自動発注は、対象業者の利用規約"
            "(自動売買/スキャルピング禁止条項) と金融商品取引法を確認の上、利用者の"
            "責任で実装してください。本ツールはデモ(DemoBroker)のみを提供します。"
        )
