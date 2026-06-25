"""戦略: 各バーで UP / DOWN / NONE のシグナルを出す.

設計方針:
  * シグナルは時刻 t において「t の確定足までの情報」だけで決める (look-ahead 禁止)。
  * バックテストでは t のシグナルに対し close[t] でエントリ、t+horizon で判定する。
  * パラメータは dict (params) で外から与え、ウォークフォワード最適化できる。

UP   = +1 : 満期に価格が上がる方に賭ける (High)
DOWN = -1 : 満期に価格が下がる方に賭ける (Low)
NONE =  0 : 取引しない (← これが勝率を上げる最大の武器。"選ぶ" こと)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import numpy as np
import pandas as pd

from . import indicators as ind

UP, DOWN, NONE = 1, -1, 0


@dataclass
class Strategy:
    name: str = "base"
    params: Dict[str, Any] = field(default_factory=dict)

    def generate(self, df: pd.DataFrame) -> pd.Series:
        """UP/DOWN/NONE の int Series を返す (index は df と一致)."""
        raise NotImplementedError

    # ウォークフォワード用: 最適化候補のパラメータ格子
    @staticmethod
    def param_grid() -> Dict[str, list]:
        return {}

    def with_params(self, **kw) -> "Strategy":
        p = dict(self.params)
        p.update(kw)
        return self.__class__(name=self.name, params=p)


class MeanReversionBB(Strategy):
    """逆張り: ボリンジャー逸脱 + RSI 過熱を確認して反対方向に賭ける.

    平均回帰が存在する局面で勝率が上がる代表格。"選んで" 撃つのでトレード数は減る。
    """

    def __init__(self, name: str = "mean_reversion", params: Dict[str, Any] | None = None):
        defaults = dict(bb_window=20, num_std=2.2, rsi_period=14, rsi_hi=70, rsi_lo=30,
                        z_window=20, z_thresh=2.0)
        super().__init__(name=name, params={**defaults, **(params or {})})

    def generate(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        close = df["close"]
        _, upper, lower = ind.bollinger(close, p["bb_window"], p["num_std"])
        r = ind.rsi(close, p["rsi_period"])
        z = ind.zscore(close, p["z_window"])

        sig = pd.Series(NONE, index=df.index, dtype=int)
        # 上に行き過ぎ → DOWN (下がる方に賭ける)
        sell = (close > upper) & (r > p["rsi_hi"]) & (z > p["z_thresh"])
        # 下に行き過ぎ → UP (上がる方に賭ける)
        buy = (close < lower) & (r < p["rsi_lo"]) & (z < -p["z_thresh"])
        sig[sell] = DOWN
        sig[buy] = UP
        return sig.fillna(NONE).astype(int)

    @staticmethod
    def param_grid() -> Dict[str, list]:
        return {
            "num_std": [1.8, 2.0, 2.2, 2.5],
            "z_thresh": [1.5, 2.0, 2.5],
            "rsi_hi": [68, 72],
            "rsi_lo": [32, 28],
        }


class TrendFollowEMA(Strategy):
    """順張り: EMA の傾き方向 + 押し目/戻りで同方向に賭ける."""

    def __init__(self, name: str = "trend_follow", params: Dict[str, Any] | None = None):
        defaults = dict(fast=10, slow=40, pullback_z=0.5, z_window=20)
        super().__init__(name=name, params={**defaults, **(params or {})})

    def generate(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        close = df["close"]
        fast = ind.ema(close, p["fast"])
        slow = ind.ema(close, p["slow"])
        z = ind.zscore(close, p["z_window"])
        up_trend = fast > slow
        dn_trend = fast < slow

        sig = pd.Series(NONE, index=df.index, dtype=int)
        # 上昇トレンド中の軽い押し目で UP
        sig[up_trend & (z < -p["pullback_z"])] = UP
        # 下降トレンド中の軽い戻りで DOWN
        sig[dn_trend & (z > p["pullback_z"])] = DOWN
        return sig.fillna(NONE).astype(int)

    @staticmethod
    def param_grid() -> Dict[str, list]:
        return {
            "fast": [8, 10, 12],
            "slow": [30, 40, 50],
            "pullback_z": [0.3, 0.5, 0.8],
        }


class RSIThreshold(Strategy):
    """素朴な RSI 逆張り (ベースライン比較用)."""

    def __init__(self, name: str = "rsi", params: Dict[str, Any] | None = None):
        defaults = dict(rsi_period=14, hi=70, lo=30)
        super().__init__(name=name, params={**defaults, **(params or {})})

    def generate(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        r = ind.rsi(df["close"], p["rsi_period"])
        sig = pd.Series(NONE, index=df.index, dtype=int)
        sig[r > p["hi"]] = DOWN
        sig[r < p["lo"]] = UP
        return sig.fillna(NONE).astype(int)

    @staticmethod
    def param_grid() -> Dict[str, list]:
        return {"rsi_period": [9, 14, 21], "hi": [70, 75, 80], "lo": [30, 25, 20]}


REGISTRY = {
    "mean_reversion": MeanReversionBB,
    "trend_follow": TrendFollowEMA,
    "rsi": RSIThreshold,
}


def get_strategy(name: str, params: Dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise ValueError(f"unknown strategy {name!r}. choose from {list(REGISTRY)}")
    return REGISTRY[name](params=params)
