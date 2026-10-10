"""Robustness: cost stress, execution lag, FX budget, risk level vs ruin (Monte Carlo)."""
import numpy as np, pandas as pd, json, pathlib
from engine import load_prices, run, metrics, Params
from wfo import walk_forward, make_params

OUT = pathlib.Path(__file__).parent / "results"; OUT.mkdir(exist_ok=True)
px = load_prices()
BASE = {"lb": "fast", "gold_long_only": True, "fx_budget": 0.0, "stop_k": 4.0}
fmt = lambda m: {k: round(float(v), 3) for k, v in m.items()}
rows = []


def rec(name, eq, start="2010"):
    m = metrics(eq[start:]); rows.append({"test": name, **fmt(m)}); print(name, fmt(m))


# 1) variants at 15% vol, 2010+
for fx in [0.0, 0.25, 0.5]:
    rec(f"fx_budget={fx}", run(px, make_params({**BASE, "fx_budget": fx}))["equity"])
for cm in [2.0, 3.0]:
    rec(f"costs x{cm}", run(px, make_params(BASE, cost_mult=cm))["equity"])
for s in ["XAUUSD", "BTCUSD"]:
    rec(f"{s} only", run(px[[s]], make_params(BASE))["equity"])
rec("gold long/short", run(px, make_params({**BASE, "gold_long_only": False}))["equity"])
rec("no dd brake", run(px, make_params(BASE, dd_brake=()))["equity"])
rec("2018+ only", run(px, make_params(BASE))["equity"], start="2018")

# 2) 1-day signal delay: run with lookback signal computed on yesterday -> approximate by lagging weights
o = run(px, make_params(BASE))
w = o["weights"].shift(1).fillna(0)
r = px.ffill().pct_change().fillna(0)
pnl = (w.shift(1) * r).sum(axis=1) - w.diff().abs().sum(axis=1) * 5e-4
rec("1-day execution delay (approx)", (1 + pnl).cumprod())

# 3) risk level sweep + walk-forward + block bootstrap Monte Carlo
rng = np.random.default_rng(42)
mc = []
for pv in [0.10, 0.15, 0.20, 0.25, 0.30]:
    oos, picks, _, _ = walk_forward(px, port_vol=pv)
    oos = oos[oos.index >= "2015-01-01"]           # period with both gold and BTC live
    eq = (1 + oos).cumprod(); m = metrics(eq)
    x = oos.values; n = len(x); H = 252 * 5; B = 20
    dd_hits = {0.3: 0, 0.5: 0}; finals = []
    for _ in range(4000):
        idx = np.concatenate([np.arange(s, s + B) % n for s in rng.integers(0, n, H // B)])
        path = np.cumprod(1 + x[idx]); dd = (path / np.maximum.accumulate(path) - 1).min()
        for k in dd_hits: dd_hits[k] += dd <= -k
        finals.append(path[-1])
    finals = np.array(finals)
    row = {"port_vol": pv, **fmt(m), "P(DD>=30%,5y)": dd_hits[0.3] / 4000, "P(DD>=50%,5y)": dd_hits[0.5] / 4000,
           "P(loss after 5y)": float((finals < 1).mean()), "median 5y multiple": float(np.median(finals)),
           "5th pct 5y multiple": float(np.percentile(finals, 5))}
    mc.append(row); print(row)
    if pv == 0.20:
        eq.to_csv(OUT / "oos_equity_vol20.csv"); pd.DataFrame(picks).to_csv(OUT / "wfo_picks.csv", index=False)
        yr = (1 + oos).groupby(oos.index.year).prod() - 1
        print("yearly OOS returns @20%:", yr.round(3).to_dict())
        yr.to_csv(OUT / "oos_yearly_vol20.csv")

pd.DataFrame(rows).to_csv(OUT / "stress.csv", index=False)
pd.DataFrame(mc).to_csv(OUT / "monte_carlo.csv", index=False)
