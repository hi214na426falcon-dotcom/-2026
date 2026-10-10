"""Walk-forward optimisation + robustness tests.

Anchored walk-forward: for each OOS year Y (2010..), choose the parameter set
with the best in-sample Sharpe over all data < Y (minimum 5 years), then trade
it in year Y only. OOS years are stitched together -> the only equity curve we
trust. Risk level (port_vol) is NOT optimised for return; it is chosen afterwards
from the Monte Carlo ruin analysis.
"""
import itertools, json, sys
import numpy as np, pandas as pd
from engine import load_prices, run, metrics, Params, CLASS_BUDGET

LOOKBACKS = {"fast": (10, 20, 40, 80), "mid": (20, 60, 120, 250), "slow": (60, 120, 250)}
GRID = {
    "lb": list(LOOKBACKS),
    "gold_long_only": [False, True],
    "fx_budget": [0.0, 0.5, 1.0],
    "stop_k": [0.0, 4.0],
}


def make_params(c, port_vol=0.15, **kw):
    lo = {"BTCUSD"} | ({"XAUUSD"} if c["gold_long_only"] else set())
    cb = dict(CLASS_BUDGET); cb["fx"] = c["fx_budget"]
    return Params(lookbacks=LOOKBACKS[c["lb"]], long_only=frozenset(lo), class_budget=cb,
                  stop_k=c["stop_k"], port_vol=port_vol, **kw)


def daily_returns(eq):
    return eq.pct_change().fillna(0.0)


def sharpe(r):
    r = r[r != 0]
    return r.mean() / r.std() * np.sqrt(252) if len(r) > 60 and r.std() > 0 else -9


def walk_forward(px, port_vol=0.15, first_oos=2010, last_oos=2026, **kw):
    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    rets = {}
    for i, c in enumerate(combos):
        rets[i] = daily_returns(run(px, make_params(c, port_vol, **kw))["equity"])
    R = pd.DataFrame(rets)
    oos, picks = [], []
    for y in range(first_oos, last_oos + 1):
        IS = R[R.index.year < y]
        IS = IS[IS.index.year >= 2005]
        scores = IS.apply(sharpe)
        best = int(scores.idxmax())
        picks.append({"year": y, **combos[best], "is_sharpe": round(float(scores.max()), 3)})
        oos.append(R.loc[R.index.year == y, best])
    oos = pd.concat(oos)
    return oos, picks, R, combos


if __name__ == "__main__":
    px = load_prices()
    oos, picks, R, combos = walk_forward(px)
    eq = (1 + oos).cumprod()
    print(pd.DataFrame(picks).to_string(index=False))
    print("OOS stitched:", {k: round(float(v), 3) for k, v in metrics(eq).items()})
    # parameter plateau: full-sample sharpe for each combo
    full = R[R.index.year >= 2010].apply(sharpe)
    tab = pd.DataFrame(combos); tab["sharpe_2010+"] = full.values
    print(tab.sort_values("sharpe_2010+", ascending=False).to_string(index=False))
