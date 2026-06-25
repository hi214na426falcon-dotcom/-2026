"""データ層: 実データCSVの読み込みと、検証用の合成データ生成.

なぜ合成データを置くのか (正直な理由):
  この実行環境からは外部の市場データ (Stooq/Yahoo/Dukascopy 等) を取得できない
  ネットワークポリシーになっています。そのため「engine と戦略ロジックが正しい
  ことの検証」には、統計的性質が既知の合成データを使います。

  - gbm_series  : ランダムウォーク (効率的市場の近似)。まともな戦略でも勝率は
                  ~50% に収束します。「エッジが無い市場」のベースライン。
  - ou_series   : 平均回帰 (Ornstein-Uhlenbeck) 系列。逆張り戦略はここで本当に
                  >50% (しばしば >60%) を出します。= 戦略が「回帰が存在するとき
                  に回帰を捉えられる」ことの証明。

  実運用の勝率を知りたい場合は、ご自身の実データCSVを load_csv で読み込んで
  ください。合成データの好成績は実市場の保証には *なりません*。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# --- カラム規約 -------------------------------------------------------------
# 内部では必ず: index=DatetimeIndex(UTC想定), columns=[open, high, low, close]
OHLC_COLS = ["open", "high", "low", "close"]


def load_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    """OHLC(V) のCSVを読み込み、標準形 DataFrame を返す.

    受け付ける列名 (大文字小文字無視) の別名:
      time/timestamp/date/datetime, open/o, high/h, low/l, close/c/price
    最低限 close (または price) があれば動作します (O/H/L が無ければ close で補完)。
    """
    df = pd.read_csv(path)
    df = _normalize_columns(df)
    if "close" not in df.columns:
        raise ValueError("CSV に close (または price) 列が必要です")

    # 時刻列をインデックスに
    time_col = next((c for c in ("time", "timestamp", "date", "datetime") if c in df.columns), None)
    if time_col is not None:
        idx = pd.to_datetime(df[time_col], utc=True, errors="coerce")
        df = df.drop(columns=[time_col]).set_index(idx)
    else:
        # 時刻列が無ければ連番を1分足とみなす
        df.index = pd.date_range("2020-01-01", periods=len(df), freq="1min", tz=tz)
    df.index.name = "time"

    # O/H/L が無ければ close から補完
    for col in ("open", "high", "low"):
        if col not in df.columns:
            df[col] = df["close"]
    df = df[OHLC_COLS + ([c for c in df.columns if c not in OHLC_COLS])]
    df = df[~df.index.isna()].sort_index()
    df[OHLC_COLS] = df[OHLC_COLS].astype(float)
    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    alias = {
        "o": "open", "open": "open",
        "h": "high", "high": "high",
        "l": "low", "low": "low",
        "c": "close", "close": "close", "price": "close", "adj close": "close",
        "time": "time", "timestamp": "time", "date": "time", "datetime": "time",
        "vol": "volume", "volume": "volume",
    }
    new_cols = {}
    for c in df.columns:
        key = str(c).strip().lower()
        new_cols[c] = alias.get(key, key)
    return df.rename(columns=new_cols)


# --- 合成データ生成 ---------------------------------------------------------
@dataclass
class SynthConfig:
    n: int = 20_000           # バー数
    start_price: float = 150.0  # 例: USD/JPY 近辺
    bar_vol: float = 0.0006   # 1バーあたりの対数リターン標準偏差 (~6pips/150)
    seed: Optional[int] = 7
    freq: str = "1min"
    start: str = "2023-01-01"


def _to_ohlc(close: np.ndarray, cfg: SynthConfig) -> pd.DataFrame:
    """close 系列から、バー内ノイズで擬似 OHLC を組む."""
    rng = np.random.default_rng(None if cfg.seed is None else cfg.seed + 1)
    n = len(close)
    prev = np.concatenate([[close[0]], close[:-1]])
    open_ = prev
    intrabar = np.abs(rng.normal(0, cfg.bar_vol * 0.5, n)) * close
    high = np.maximum(open_, close) + intrabar
    low = np.minimum(open_, close) - intrabar
    idx = pd.date_range(cfg.start, periods=n, freq=cfg.freq, tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close}, index=idx
    ).rename_axis("time")


def gbm_series(cfg: SynthConfig | None = None) -> pd.DataFrame:
    """幾何ブラウン運動 (ランダムウォーク). エッジの無い「効率的市場」ベースライン."""
    cfg = cfg or SynthConfig()
    rng = np.random.default_rng(cfg.seed)
    rets = rng.normal(0.0, cfg.bar_vol, cfg.n)
    close = cfg.start_price * np.exp(np.cumsum(rets))
    return _to_ohlc(close, cfg)


def ou_series(
    cfg: SynthConfig | None = None,
    theta: float = 0.02,
    drift_vol: float = 0.00008,
) -> pd.DataFrame:
    """平均回帰 (Ornstein-Uhlenbeck) 系列.

    log価格が、ゆっくり動く平均 mu に向かって速度 theta で回帰する。
    theta が大きいほど回帰が強い (逆張りが効く)。drift_vol は平均自体の漂流。
    これは「平均回帰が存在する市場」を模した *デモ用* データ。実市場の保証ではない。
    """
    cfg = cfg or SynthConfig()
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n
    x = np.zeros(n)          # log価格 - 平均 の乖離
    mu = np.zeros(n)         # ゆっくり動く平均 (log)
    mu[0] = np.log(cfg.start_price)
    for t in range(1, n):
        mu[t] = mu[t - 1] + rng.normal(0, drift_vol)
        x[t] = x[t - 1] - theta * x[t - 1] + rng.normal(0, cfg.bar_vol)
    close = np.exp(mu + x)
    return _to_ohlc(close, cfg)


def make_sample(kind: str = "ou", n: int = 20_000, seed: int = 7) -> pd.DataFrame:
    cfg = SynthConfig(n=n, seed=seed)
    if kind == "gbm":
        return gbm_series(cfg)
    if kind == "ou":
        return ou_series(cfg)
    raise ValueError(f"unknown kind: {kind!r} (use 'ou' or 'gbm')")


def save_csv(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out.insert(0, "time", out.index.strftime("%Y-%m-%d %H:%M:%S"))
    out.to_csv(path, index=False)
