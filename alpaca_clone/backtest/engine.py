"""バックテスタ。

各確定足でエンジンにシグナルを求め、シグナルが出たらバイナリー取引を模擬する:
- エントリー価格 = シグナルが出た足の終値
- 決済価格      = expiry_bars 本後の足の終値
- 勝ち: CALL かつ 決済>エントリー / PUT かつ 決済<エントリー
- ペイアウト: 勝ち = stake * payout_rate, 負け = -stake, 同値 = 0(返金)

同時に複数ポジションは持たない(1 取引が決済するまで次は取らない)。
cooldown_bars でシグナル後の待機も設定できる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..core.models import AccountState, Candle, Direction, Trade, TradeOutcome
from ..strategy.engine import StrategyConfig, build_engine


@dataclass
class BacktestResult:
    """バックテストの成績。"""

    trades: List[Trade] = field(default_factory=list)
    starting_balance: float = 1000.0
    ending_balance: float = 1000.0
    equity_curve: List[float] = field(default_factory=list)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.outcome is TradeOutcome.WIN)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.trades if t.outcome is TradeOutcome.LOSS)

    @property
    def ties(self) -> int:
        return sum(1 for t in self.trades if t.outcome is TradeOutcome.TIE)

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return self.wins / decided if decided else 0.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def net_pnl(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def expectancy(self) -> float:
        """1 取引あたりの期待損益。"""
        return sum(t.pnl for t in self.trades) / self.n_trades if self.n_trades else 0.0

    @property
    def max_drawdown(self) -> float:
        """エクイティカーブの最大ドローダウン(金額)。"""
        peak = float("-inf")
        mdd = 0.0
        for v in self.equity_curve:
            peak = max(peak, v)
            mdd = max(mdd, peak - v)
        return mdd

    @property
    def max_consecutive_losses(self) -> int:
        streak = worst = 0
        for t in self.trades:
            if t.outcome is TradeOutcome.LOSS:
                streak += 1
                worst = max(worst, streak)
            elif t.outcome is TradeOutcome.WIN:
                streak = 0
        return worst

    def required_win_rate(self, payout_rate: float) -> float:
        """このペイアウトで損益分岐となる勝率(参考値)。"""
        return 1.0 / (1.0 + payout_rate)

    def summary(self) -> Dict[str, object]:
        pr = self.trades[0].payout_rate if self.trades else 0.85
        return {
            "trades": self.n_trades,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "win_rate": round(self.win_rate, 4),
            "breakeven_win_rate": round(self.required_win_rate(pr), 4),
            "profit_factor": (round(self.profit_factor, 4)
                              if self.profit_factor != float("inf") else "inf"),
            "expectancy": round(self.expectancy, 4),
            "net_pnl": round(self.net_pnl, 2),
            "starting_balance": round(self.starting_balance, 2),
            "ending_balance": round(self.ending_balance, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
        }


class Backtester:
    def __init__(
        self,
        config: StrategyConfig,
        starting_balance: float = 1000.0,
        stake: float = 10.0,
        stake_mode: str = "fixed",  # "fixed" | "percent"
    ):
        self.config = config
        self.starting_balance = starting_balance
        self.stake = stake
        self.stake_mode = stake_mode

    def _stake_for(self, balance: float) -> float:
        if self.stake_mode == "percent":
            return max(0.0, balance * (self.stake / 100.0))
        return self.stake

    def run(self, candles: Sequence[Candle]) -> BacktestResult:
        engine = build_engine(self.config, candles)
        account = AccountState(balance=self.starting_balance)
        result = BacktestResult(
            starting_balance=self.starting_balance,
            ending_balance=self.starting_balance,
        )
        result.equity_curve.append(account.balance)

        expiry = max(1, self.config.expiry_bars)
        cooldown = max(0, self.config.cooldown_bars)
        n = len(candles)
        # 満期の足が存在する範囲まで走査
        i = engine.warmup
        busy_until = -1  # この index までは新規エントリーしない
        while i < n - expiry:
            if i <= busy_until:
                i += 1
                continue

            signal = engine.evaluate(i)
            if not signal.is_trade:
                i += 1
                continue

            entry_price = candles[i].close
            settle_index = i + expiry
            exit_price = candles[settle_index].close
            stake = self._stake_for(account.balance)
            if stake <= 0:
                break  # 残高が尽きた

            trade = Trade(
                entry_time=candles[i].timestamp,
                direction=signal.direction,
                entry_price=entry_price,
                expiry_bars=expiry,
                stake=stake,
                payout_rate=self.config.payout_rate,
                reason=signal.reason,
            )
            trade.settle(exit_price, candles[settle_index].timestamp)
            account.apply(trade)
            result.trades.append(trade)
            result.equity_curve.append(account.balance)

            # 決済まで拘束 + クールダウン
            busy_until = settle_index + cooldown
            i += 1

        result.ending_balance = account.balance
        return result
