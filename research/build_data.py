"""Build daily OHLC dataset for XAUUSD, BTCUSD and FX majors from public GitHub sources.

Sources (cloned into SRC):
  - BaseMax/XAUUSD-LSTM            XAU_15m_data.csv  (2004-06 .. 2025-09, 15m OHLC)
  - ff137/bitstamp-btcusd-minute-data  (2012 .. 2026, 1m OHLC, Bitstamp)
  - datasets/exchange-rates        data/daily.csv  (FRED H.10 noon rates, 1971 .. 2026, close only)
Output: research/data/daily_<SYM>.csv with Date,Open,High,Low,Close
"""
import sys, gzip, pandas as pd, numpy as np, pathlib
SRC = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(__file__).parent / "data"

def to_daily(df):
    d = df.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    return d

# Gold
g = pd.read_csv(SRC/"BaseMax_XAUUSD-LSTM/XAU_15m_data.csv", sep=";")
g.index = pd.to_datetime(g["Date"], format="%Y.%m.%d %H:%M"); g = g.drop(columns=["Date", "Volume"])
g = to_daily(g); g = g[g.index.dayofweek < 5]
g.to_csv(OUT/"daily_XAUUSD.csv", index_label="Date")

# BTC
parts = []
for f in [SRC/"ff137_bitstamp-btcusd-minute-data/data/historical/btcusd_bitstamp_1min_2012-2025.csv.gz",
          SRC/"ff137_bitstamp-btcusd-minute-data/data/updates/btcusd_bitstamp_1min_latest.csv"]:
    b = pd.read_csv(f, usecols=["timestamp", "open", "high", "low", "close"])
    parts.append(b)
b = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp")
b.index = pd.to_datetime(b["timestamp"], unit="s"); b = b.drop(columns="timestamp")
b.columns = ["Open", "High", "Low", "Close"]
b = to_daily(b); b = b[b.index >= "2014-01-01"]
b.to_csv(OUT/"daily_BTCUSD.csv", index_label="Date")

# FX (close only; values are local currency per USD; O/H/L approximated by close -> engine uses close-to-close only)
fx = pd.read_csv(SRC/"datasets_exchange-rates/data/daily.csv")
fx["Date"] = pd.to_datetime(fx["Date"])
piv = fx.pivot_table(index="Date", columns="Country", values="Exchange rate")
m = {"EURUSD": ("Euro", True), "GBPUSD": ("United Kingdom", True), "AUDUSD": ("Australia", True),
     "USDJPY": ("Japan", False), "USDCAD": ("Canada", False), "USDCHF": ("Switzerland", False)}
for sym, (c, inv) in m.items():
    s = piv[c].dropna(); s = s[s.index >= "2004-01-01"]
    if inv: s = 1.0 / s  # dataset quotes foreign units per USD
    d = pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s})
    d.to_csv(OUT/f"daily_{sym}.csv", index_label="Date")
for f in sorted(OUT.glob("*.csv")):
    d = pd.read_csv(f); print(f.name, len(d), d.Date.iloc[0], d.Date.iloc[-1], d.Close.iloc[-1])
