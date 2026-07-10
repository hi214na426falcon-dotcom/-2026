"""通貨ペアごと・時間帯ごとの統計を、バックテストから決定論的に計算する。

これがスカウトの「事実の土台」。LLM はここで出た数字に根拠づけられた説明を
付けるだけで、勝率そのものを創作しない（＝数字の捏造をしない）。

データの入手:
- ``data/m1/<PAIR>.csv`` または ``data/m1/<PAIR>_*.csv`` があれば実データを使う。
- 無ければ合成データ（ペアごとに別シード）で動作確認する。合成データの結果は
  ``is_synthetic=True`` として明示し、実弾の根拠には使えないことを分かるようにする。
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from backtest.data import Series, generate_synthetic, load_csv
from backtest.engine import run_backtest
from backtest.sessions import (
    DEFAULT_SLOTS_JST,
    MASTER_SESSIONS_JST,
    bucket_by_slot,
    restrict_signals_to_sessions,
    slot_label,
)
from backtest.strategies import STRATEGIES

# 調査対象の既定ペア（BABA/theoption で一般的な主要ペア。調査結果が出たら差し替え）。
DEFAULT_PAIRS: List[str] = ["USDJPY", "EURJPY", "GBPJPY", "EURUSD", "AUDJPY"]

# ペアごとの概算スタート価格（合成データ用の見た目合わせ。実データがあれば無視）。
_START_PRICE = {
    "USDJPY": 157.0,
    "EURJPY": 170.0,
    "GBPJPY": 200.0,
    "EURUSD": 1.08,
    "AUDJPY": 104.0,
    "GBPUSD": 1.27,
}


@dataclass
class SlotStat:
    """ある (ペア, 時間帯) の成績。"""

    pair: str
    slot: Tuple[int, int]
    win_rate: float
    edge: float
    trades: int
    ci_low: float
    ci_high: float
    breakeven: float
    significant_plus: bool
    is_synthetic: bool

    @property
    def slot_label(self) -> str:
        return slot_label(self.slot)


def find_pair_files(pair: str, data_dir: str) -> List[str]:
    """data_dir 内の <PAIR>.csv(.gz) / <PAIR>_*.csv(.gz) を探す（大文字小文字無視）。"""
    if not os.path.isdir(data_dir):
        return []
    found: List[str] = []
    for pattern in ("*.csv", "*.csv.gz"):
        for path in sorted(glob.glob(os.path.join(data_dir, pattern))):
            base = os.path.basename(path).lower()
            if base.endswith(".gz"):
                base = base[:-3]
            p = pair.lower()
            if base == f"{p}.csv" or base.startswith(f"{p}_") or base.startswith(f"{p}-"):
                found.append(path)
    return found


def load_pair_series(
    pair: str,
    data_dir: str = "data/m1",
    synthetic_bars: int = 6000,
    process: str = "randomwalk",
    seed_base: int = 100,
) -> Tuple[Series, bool]:
    """ペアの Series を得る。実データが無ければ合成。戻り値 (series, is_synthetic)。"""
    files = find_pair_files(pair, data_dir)
    if files:
        bars = []
        name = pair
        for f in files:
            s = load_csv(f, name=pair)
            bars.extend(s.bars)
        return Series(bars, name=name), False
    # 合成データ（ペアごとに別シード → ペアで結果がばらつく）
    seed = seed_base + sum(ord(c) for c in pair)
    series = generate_synthetic(
        n=synthetic_bars,
        start_price=_START_PRICE.get(pair, 150.0),
        seed=seed,
        process=process,
        bar_minutes=1,
    )
    series.name = pair
    return series, True


def analyze_pair(
    pair: str,
    strategy: str = "bollinger",
    strategy_kwargs: Optional[dict] = None,
    expiry_min: int = 3,
    payout: float = 1.90,
    slots: Sequence[Tuple[int, int]] = tuple(DEFAULT_SLOTS_JST),
    sessions: Sequence[Tuple[int, int]] = tuple(MASTER_SESSIONS_JST),
    data_dir: str = "data/m1",
    tz_offset_hours: int = 9,
    process: str = "randomwalk",
) -> Dict[Tuple[int, int], SlotStat]:
    """1 ペアを時間帯ごとに集計する。"""
    if strategy not in STRATEGIES:
        raise ValueError(f"未知の戦略: {strategy}（利用可: {', '.join(STRATEGIES)}）")
    series, is_syn = load_pair_series(pair, data_dir, process=process)
    fn = STRATEGIES[strategy]
    if strategy == "random":
        signals = fn(series, seed=7)
    else:
        signals = fn(series, **(strategy_kwargs or {}))
    # MASTER_PROMPT の時間帯（夜＋深夜）だけに絞る
    times = [b.time for b in series.bars]
    signals = restrict_signals_to_sessions(times, signals, sessions, tz_offset_hours)
    res = run_backtest(
        series, signals, payout=payout, expiry_bars=expiry_min, no_overlap=True, name=pair
    )
    buckets = bucket_by_slot(res.trades, slots, payout=payout, tz_offset_hours=tz_offset_hours)
    out: Dict[Tuple[int, int], SlotStat] = {}
    for slot, st in buckets.items():
        out[slot] = SlotStat(
            pair=pair,
            slot=slot,
            win_rate=st["win_rate"],
            edge=st["edge"],
            trades=int(st["trades"]),
            ci_low=st["ci_low"],
            ci_high=st["ci_high"],
            breakeven=st["breakeven"],
            significant_plus=bool(st["significant_plus"]),
            is_synthetic=is_syn,
        )
    return out


def analyze_pairs(
    pairs: Sequence[str] = tuple(DEFAULT_PAIRS),
    **kwargs,
) -> Dict[str, Dict[Tuple[int, int], SlotStat]]:
    """複数ペアを一括で分析する。"""
    return {pair: analyze_pair(pair, **kwargs) for pair in pairs}


def rank_by_slot(
    analysis: Dict[str, Dict[Tuple[int, int], SlotStat]],
    slots: Sequence[Tuple[int, int]] = tuple(DEFAULT_SLOTS_JST),
    min_trades: int = 30,
) -> Dict[Tuple[int, int], List[SlotStat]]:
    """時間帯ごとに、エッジ（損益分岐との差）が高い順にペアを並べる。

    サンプルが ``min_trades`` 未満の (ペア, 時間帯) は「参考」として末尾に回す。
    """
    ranking: Dict[Tuple[int, int], List[SlotStat]] = {}
    for slot in slots:
        rows = [a[slot] for a in analysis.values() if slot in a]
        # 十分なサンプルがあるものを優先し、その中でエッジ降順
        rows.sort(key=lambda s: (s.trades >= min_trades, s.edge), reverse=True)
        ranking[slot] = rows
    return ranking
