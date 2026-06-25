"""正直な指標の検証."""
import math

import pandas as pd

from binbot.metrics import wilson_interval, break_even_winrate, compute_stats


def test_break_even_winrate():
    assert math.isclose(break_even_winrate(0.85), 1 / 1.85, rel_tol=1e-9)
    assert math.isclose(break_even_winrate(1.0), 0.5, rel_tol=1e-9)
    assert break_even_winrate(0.80) > 0.55  # ペイアウト80%なら55%超必要


def test_wilson_small_sample_is_wide():
    lo_big, hi_big = wilson_interval(60, 100)
    lo_small, hi_small = wilson_interval(12, 20)  # 同じ60%でも少数
    assert lo_big < 0.60 < hi_big
    assert (hi_small - lo_small) > (hi_big - lo_big)  # 少数の方が区間が広い


def _trades(n_win, n_loss, payout=0.85, n_push=0):
    rows = []
    for _ in range(n_win):
        rows.append({"outcome": "win", "pnl": payout})
    for _ in range(n_loss):
        rows.append({"outcome": "loss", "pnl": -1.0})
    for _ in range(n_push):
        rows.append({"outcome": "push", "pnl": 0.0})
    return pd.DataFrame(rows)


def test_expectancy_and_edge():
    st = compute_stats(_trades(60, 40), payout=0.85)
    assert st.win_rate == 0.60
    assert math.isclose(st.expectancy, (60 * 0.85 - 40) / 100, rel_tol=1e-9)
    assert st.edge_vs_breakeven > 0  # 60% > 54.05% なので理論上プラス


def test_below_breakeven_is_negative_edge():
    # 勝率52% はペイアウト85%(分岐54%)に届かず理論上マイナス
    st = compute_stats(_trades(52, 48), payout=0.85)
    assert st.edge_vs_breakeven < 0
    assert st.expectancy < 0


def test_push_excluded_from_winrate():
    st = compute_stats(_trades(50, 50, n_push=10), payout=0.85)
    assert st.n_trades == 100      # push は分母に入らない
    assert st.n_push == 10
    assert st.win_rate == 0.5
