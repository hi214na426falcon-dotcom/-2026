"""ペーパートレード自動売買ループ (デモ).

これが「自動売買アプリ」の本体です。ただし発注先は DemoBroker (シミュレーション)。
実弾は流れません。ロジックは実運用とほぼ同じ:

  毎バー:
    1. 直近の確定足までの履歴 (visible) を取得
    2. 戦略がシグナル UP/DOWN/NONE を判定
    3. NONE 以外、かつ建玉が無ければ発注
    4. 時間を1バー進め、満期が来た建玉を決済

資金管理: 既定は固定ステーク。risk_pct を指定すると残高比例のステークも可能。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from .backtest import BacktestConfig, estimate_bars_per_day
from .broker import DemoBroker
from .strategy import Strategy, NONE
from . import metrics as M


@dataclass
class PaperConfig:
    warmup: int = 200          # 指標が安定するまで取引しない
    lookback: int = 500        # 戦略に渡す直近バー数 (ローリングバッファ)
    stake: float = 1.0         # 固定ステーク
    risk_pct: float = 0.0      # >0 なら残高×risk_pct をステークに (固定より優先)
    max_steps: Optional[int] = None
    verbose: bool = False


def _stake_for(cfg: PaperConfig, balance: float) -> float:
    if cfg.risk_pct and cfg.risk_pct > 0:
        return max(0.0, balance * cfg.risk_pct)
    return cfg.stake


def run_paper(prices: pd.DataFrame, strategy: Strategy,
              bt_cfg: BacktestConfig | None = None,
              cfg: PaperConfig | None = None,
              balance: float = 100_000.0):
    """戻り値: (broker, trades_df, Stats)."""
    bt_cfg = bt_cfg or BacktestConfig()
    cfg = cfg or PaperConfig()
    broker = DemoBroker(prices, balance=balance, payout=bt_cfg.payout,
                        tie=bt_cfg.tie, one_position=bt_cfg.one_position)

    steps = 0
    while True:
        if cfg.max_steps is not None and steps >= cfg.max_steps:
            break
        i = broker.cursor
        if i >= cfg.warmup:
            df_vis = broker.visible(lookback=cfg.lookback)
            if len(df_vis) >= 30 and not broker.has_open_position():
                sig = int(strategy.generate(df_vis).iloc[-1])
                if sig != NONE:
                    stake = _stake_for(cfg, broker.get_balance())
                    if stake > 0:
                        order = broker.place_binary_order(sig, stake, bt_cfg.horizon)
                        if cfg.verbose:
                            print(f"[{order.entry_time}] {order.direction if isinstance(order.direction,str) else ('UP' if sig==1 else 'DOWN')} "
                                  f"@ {order.entry_price:.5f} stake={stake:.2f}")
        if not broker.step():
            break
        steps += 1

    broker.finalize()
    trades = broker.trades_df()
    stats = M.compute_stats(trades, payout=bt_cfg.payout,
                            bars_per_day=estimate_bars_per_day(prices))
    return broker, trades, stats
