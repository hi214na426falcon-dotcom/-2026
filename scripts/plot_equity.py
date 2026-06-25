"""取引CSV (reports/*.trades.csv) からエクイティカーブとドローダウンを描画.

使い方:
  PYTHONPATH=src python scripts/plot_equity.py reports/paper_rsi_ou.trades.csv reports/equity.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main(csv_path: str, out_path: str) -> None:
    df = pd.read_csv(csv_path)
    pnl = df["pnl"].to_numpy(dtype=float)
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak

    wins = (df["outcome"] == "win").sum()
    decided = (df["outcome"].isin(["win", "loss"])).sum()
    wr = wins / decided if decided else float("nan")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(equity, lw=1.3, color="#1f77b4")
    ax1.axhline(0, color="gray", lw=0.8, ls="--")
    ax1.set_title(f"Equity curve - {Path(csv_path).stem}  "
                  f"(trades={decided}, win rate={wr:.1%})  [SYNTHETIC DATA - reference only]")
    ax1.set_ylabel("Cumulative P&L (stake units)")
    ax1.grid(alpha=0.3)

    ax2.fill_between(range(len(dd)), dd, 0, color="#d62728", alpha=0.5)
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Trade #")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    print(f"saved -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
