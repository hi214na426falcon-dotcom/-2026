"""Daily backtest engine for the multi-asset volatility-targeted trend ensemble.

The logic here mirrors MQL5/Experts/MultiAssetTrendVT.mq5 one-to-one so that the
Python results are a faithful proxy of what the EA does on D1 bars.

Strategy (evidence base in research/README.md):
  1. Signal  = average of sign(Close_t / Close_{t-L} - 1) over an ensemble of
               lookbacks L (time-series momentum, Moskowitz/Ooi/Pedersen 2012,
               Hurst/Ooi/Pedersen 2017). Value in [-1, 1]; no parameter is
               "the" lookback, which limits curve fitting.
  2. Sizing  = signal * (asset_vol_target / EWMA realised vol) (volatility
               targeting, Moreira & Muir 2017, Harvey et al. 2018), then the
               whole book is scaled so ex-ante portfolio vol == portfolio target.
  3. Risk    = per-asset leverage caps, catastrophic stop at K x daily vol x
               sqrt(...) from entry, and a drawdown brake that halves / quarters
               risk when equity is X% below peak (no martingale, no averaging down).
  4. Costs   = spread+slippage per unit of notional traded, plus overnight
               financing per year of notional held (CFD swap).
"""
from __future__ import annotations
import pathlib
from dataclasses import dataclass, field, replace
import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).parent / "data"

# symbol -> (asset class, max leverage per asset (notional/equity), spread+slip bps, financing %/yr, allow short)
UNIVERSE = {
    "XAUUSD": ("gold",   2.0,  3.0,  3.0, True),
    "BTCUSD": ("crypto", 0.6, 12.0, 12.0, False),
    "EURUSD": ("fx",     4.0,  1.0,  1.0, True),
    "GBPUSD": ("fx",     4.0,  1.5,  1.0, True),
    "AUDUSD": ("fx",     4.0,  1.5,  1.0, True),
    "USDJPY": ("fx",     4.0,  1.2,  1.0, True),
    "USDCAD": ("fx",     4.0,  2.0,  1.0, True),
    "USDCHF": ("fx",     4.0,  2.0,  1.0, True),
}
CLASS_BUDGET = {"gold": 1.0, "crypto": 1.0, "fx": 1.0}   # equal risk per asset class


def load_prices(symbols=None) -> pd.DataFrame:
    symbols = symbols or list(UNIVERSE)
    cols = {}
    for s in symbols:
        d = pd.read_csv(DATA / f"daily_{s}.csv", parse_dates=["Date"], index_col="Date")
        cols[s] = d["Close"]
    px = pd.DataFrame(cols)
    px = px[px.index.dayofweek < 5]                         # EA trades on weekday D1 bars
    px = px[px.index >= "2004-06-15"]
    return px


@dataclass(frozen=True)
class Params:
    lookbacks: tuple = (20, 60, 120, 250)
    port_vol: float = 0.15            # annual portfolio volatility target
    vol_span: int = 60                # EWMA span for realised vol (days)
    cov_window: int = 120             # window for ex-ante portfolio vol
    stop_k: float = 0.0               # catastrophic stop: K * daily vol * price; 0 = off
    stop_cooldown: int = 10           # days flat after a stop
    dd_brake: tuple = ((0.15, 0.5), (0.25, 0.25))   # (drawdown, risk multiplier)
    rebalance_buffer: float = 0.25    # trade only if |target-current| > buffer*|target|
    long_only: frozenset = frozenset({"BTCUSD"})
    cost_mult: float = 1.0            # stress multiplier on spread & financing
    max_gross: float = 6.0            # gross leverage cap for whole account
    class_budget: dict = field(default_factory=lambda: dict(CLASS_BUDGET))


def run(px: pd.DataFrame, p: Params, start=None, end=None) -> dict:
    syms = list(px.columns)
    n = len(syms)
    P = px.ffill().values
    valid = ~np.isnan(P)
    R = np.zeros_like(P)
    R[1:] = P[1:] / P[:-1] - 1.0
    R[~valid] = 0.0
    R[np.isnan(R)] = 0.0
    T = len(px)

    # EWMA variance of daily returns
    alpha = 2.0 / (p.vol_span + 1)
    var = np.full((T, n), np.nan)
    v = np.full(n, np.nan)
    for t in range(1, T):
        r = R[t]
        v = np.where(np.isnan(v), r * r, (1 - alpha) * v + alpha * r * r)
        var[t] = v
    dvol = np.sqrt(var)
    # floor on vol so a quiet regime cannot blow up leverage (use 0.5x of 1y median)
    med = pd.DataFrame(dvol).rolling(250, min_periods=60).median().values
    dvol = np.fmax(dvol, 0.5 * np.nan_to_num(med, nan=0.0))

    # ensemble TSMOM signal
    sig = np.zeros((T, n))
    for L in p.lookbacks:
        past = np.vstack([np.full((L, n), np.nan), P[:-L]])
        s = np.sign(P / past - 1.0)
        sig += np.nan_to_num(s)
    sig /= len(p.lookbacks)
    maxL = max(p.lookbacks)

    cls = [UNIVERSE[s][0] for s in syms]
    lev_cap = np.array([UNIVERSE[s][1] for s in syms])
    spread = np.array([UNIVERSE[s][2] for s in syms]) * 1e-4 * p.cost_mult
    fin = np.array([UNIVERSE[s][3] for s in syms]) * 1e-2 / 252 * p.cost_mult
    can_short = np.array([UNIVERSE[s][4] and s not in p.long_only for s in syms])

    # per-asset vol target: split class budget among live members, then scale to portfolio vol
    rets = pd.DataFrame(R)
    w = np.zeros(n)                    # current notional / equity
    eq = 1.0
    peak = 1.0
    equity = np.ones(T)
    gross = np.zeros(T)
    turnover = np.zeros(T)
    cost_t = np.zeros(T)
    W = np.zeros((T, n))
    entry = np.full(n, np.nan)
    cool = np.zeros(n, dtype=int)
    stops = 0

    for t in range(1, T):
        # 1) P&L from holding w over (t-1, t]
        pnl = np.dot(w, R[t]) - np.dot(np.abs(w), fin)
        eq *= (1.0 + pnl)
        # mark-to-market weight drift
        w = w * (1.0 + R[t]) / (1.0 + pnl) if eq > 0 else w * 0
        equity[t] = eq
        peak = max(peak, eq)
        if eq <= 0:
            equity[t:] = 0
            break

        # 2) catastrophic stops (checked on close)
        if p.stop_k > 0:
            for i in range(n):
                if w[i] != 0 and not np.isnan(entry[i]):
                    dist = p.stop_k * dvol[t - 1, i] * entry[i] * np.sqrt(5)
                    if (w[i] > 0 and P[t, i] < entry[i] - dist) or (w[i] < 0 and P[t, i] > entry[i] + dist):
                        c = abs(w[i]) * spread[i]
                        eq *= (1 - c); cost_t[t] += c; turnover[t] += abs(w[i])
                        w[i] = 0.0; entry[i] = np.nan; cool[i] = p.stop_cooldown; stops += 1

        # 3) target weights
        live = valid[t] & (np.arange(T)[t] >= maxL) & ~np.isnan(dvol[t])
        tgt = np.zeros(n)
        if live.any():
            budgets = np.zeros(n)
            for c in set(cls):
                members = [i for i in range(n) if cls[i] == c and live[i]]
                if members:
                    for i in members:
                        budgets[i] = p.class_budget[c] / len(members)
            budgets /= budgets.sum()
            raw = sig[t] * budgets / (dvol[t] * np.sqrt(252))
            raw = np.where(can_short, raw, np.maximum(raw, 0))
            raw[~live] = 0
            raw[cool > 0] = 0
            lo = max(1, t - p.cov_window)
            C = np.cov(R[lo:t + 1].T) * 252 if t - lo > 20 else np.diag((dvol[t] ** 2) * 252)
            C = np.atleast_2d(np.nan_to_num(C))
            pv = np.sqrt(max(raw @ C @ raw, 1e-12))
            tgt = raw * (p.port_vol / pv) if pv > 1e-6 else raw * 0
            # drawdown brake
            dd = 1 - eq / peak
            mult = 1.0
            for lvl, m in p.dd_brake:
                if dd >= lvl:
                    mult = m
            tgt *= mult
            tgt = np.clip(tgt, -lev_cap, lev_cap)
            g = np.abs(tgt).sum()
            if g > p.max_gross:
                tgt *= p.max_gross / g
        cool = np.maximum(cool - 1, 0)

        # 4) trade with buffer (always trade if sign flips or target is 0)
        for i in range(n):
            need = (np.sign(tgt[i]) != np.sign(w[i])) or abs(tgt[i] - w[i]) > p.rebalance_buffer * abs(tgt[i])
            if need:
                dw = abs(tgt[i] - w[i])
                if dw > 1e-9:
                    if np.sign(tgt[i]) != np.sign(w[i]) and tgt[i] != 0:
                        entry[i] = P[t, i]
                    if tgt[i] == 0:
                        entry[i] = np.nan
                    c = dw * spread[i]
                    eq *= (1 - c); cost_t[t] += c; turnover[t] += dw
                    w[i] = tgt[i]
        equity[t] = eq
        W[t] = w
        gross[t] = np.abs(w).sum()

    eqs = pd.Series(equity, index=px.index)
    out = {"equity": eqs, "weights": pd.DataFrame(W, index=px.index, columns=syms),
           "gross": pd.Series(gross, index=px.index), "turnover": pd.Series(turnover, index=px.index),
           "costs": pd.Series(cost_t, index=px.index), "stops": stops}
    return out


def metrics(eq: pd.Series) -> dict:
    eq = eq[eq > 0]
    r = eq.pct_change().dropna()
    if len(r) < 20:
        return {}
    yrs = len(r) / 252
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    dd = (eq / eq.cummax() - 1).min()
    down = r[r < 0].std() * np.sqrt(252)
    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "Sortino": r.mean() * 252 / down if down > 0 else 0,
            "MaxDD": dd, "Calmar": cagr / abs(dd) if dd < 0 else np.inf, "Years": yrs}
