"""ペーパートレーダー: 確定足を 1 本ずつ受け取り、シグナルに従って仮想発注する。

同期処理として実装(テスト容易)。ライブ運用のスレッド/待機はサーバー側が担当する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..core.models import Candle, Direction, Trade, TradeOutcome
from ..execution.broker import Broker, Order, PaperBroker
from ..strategy.engine import StrategyConfig, build_engine

EventCB = Callable[[dict], None]


@dataclass
class _Pending:
    trade: Trade
    settle_index: int


class PaperTrader:
    def __init__(
        self,
        config: StrategyConfig,
        broker: Optional[Broker] = None,
        stake: float = 10.0,
        stake_mode: str = "fixed",   # "fixed" | "percent"
        on_event: Optional[EventCB] = None,
    ):
        self.config = config
        self.broker = broker or PaperBroker(starting_balance=1000.0)
        self.stake = stake
        self.stake_mode = stake_mode
        self.on_event = on_event

        self.history: List[Candle] = []
        self.pending: List[_Pending] = []
        self.last_signal_dir: Direction = Direction.NONE
        self._busy_until_index: int = -1  # 決済+クールダウンまで新規なし

    # ---- 外部から 1 本供給 -----------------------------------------
    def feed_candle(self, candle: Candle) -> None:
        self.history.append(candle)
        cur = len(self.history) - 1

        self._settle_due(cur)
        self._maybe_enter(cur)

    def _settle_due(self, cur: int) -> None:
        still: List[_Pending] = []
        for p in self.pending:
            if cur >= p.settle_index:
                exit_price = self.history[p.settle_index].close
                self.broker.settle(p.trade, exit_price,
                                    self.history[p.settle_index].timestamp)
                self._emit("settle", trade=p.trade)
            else:
                still.append(p)
        self.pending = still

    def _maybe_enter(self, cur: int) -> None:
        if self.pending:  # 1 ポジション制
            return
        if cur <= self._busy_until_index:
            return

        engine = build_engine(self.config, self.history)
        if cur < engine.warmup:
            return

        signal = engine.evaluate(cur)
        self.last_signal_dir = signal.direction
        if not signal.is_trade:
            return

        expiry = max(1, self.config.expiry_bars)
        # 満期の足はまだ未来 → 未決済ポジションとして保持
        entry_price = self.history[cur].close
        stake = self._stake_for(self.broker_balance())
        if stake <= 0:
            self._emit("no-funds")
            return

        order = Order(
            direction=signal.direction,
            stake=stake,
            expiry_bars=expiry,
            entry_price=entry_price,
            entry_time=self.history[cur].timestamp,
            payout_rate=self.config.payout_rate,
            reason=signal.reason,
        )
        try:
            trade = self.broker.place(order)
        except ValueError as exc:
            self._emit("reject", message=str(exc))
            return

        settle_index = cur + expiry
        self.pending.append(_Pending(trade=trade, settle_index=settle_index))
        self._busy_until_index = settle_index + max(0, self.config.cooldown_bars)
        self._emit("enter", trade=trade)

    # ---- ヘルパ -----------------------------------------------------
    def _stake_for(self, balance: float) -> float:
        if self.stake_mode == "percent":
            return max(0.0, balance * (self.stake / 100.0))
        return self.stake

    def broker_balance(self) -> float:
        if isinstance(self.broker, PaperBroker):
            return self.broker.balance
        return float("inf")

    def _emit(self, kind: str, **extra) -> None:
        if self.on_event is None:
            return
        payload: Dict[str, object] = {"kind": kind}
        trade = extra.pop("trade", None)
        if isinstance(trade, Trade):
            payload["trade"] = {
                "direction": trade.direction.value,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "outcome": trade.outcome.value,
                "pnl": round(trade.pnl, 4),
                "reason": trade.reason,
                "entry_time": trade.entry_time,
            }
        payload.update(extra)
        self.on_event(payload)

    # ---- 状態(ダッシュボード用) -----------------------------------
    def state(self) -> Dict[str, object]:
        broker = self.broker
        closed = getattr(broker, "closed_trades", [])
        recent = [
            {
                "direction": t.direction.value,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "outcome": t.outcome.value,
                "pnl": round(t.pnl, 4),
                "entry_time": t.entry_time,
            }
            for t in closed[-20:]
        ]
        wins = sum(1 for t in closed if t.outcome is TradeOutcome.WIN)
        losses = sum(1 for t in closed if t.outcome is TradeOutcome.LOSS)
        decided = wins + losses
        return {
            "strategy": self.config.name,
            "candles_seen": len(self.history),
            "balance": round(self.broker_balance(), 2),
            "open_positions": len(self.pending),
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / decided, 4) if decided else 0.0,
            "last_signal": self.last_signal_dir.value,
            "recent_trades": recent,
        }
