#!/usr/bin/env python3
"""15秒取引（実質ペイアウト2.05倍）の損益構造分析。

data/s15/<PAIR>.csv.gz（Dukascopyティック→15秒足, fetch-ticks.yml が生成）を使い、
以下を定量化する:

1. 同値率 — 15秒後に価格が動かない確率（同値=負けルールの影響）
2. ランダム方向のEV — ペイアウト2.05でもコイン投げが負ける理由
3. 戦略成績（摩擦ゼロのミッド価格） — 見かけのエッジ
4. 丸め/マークアップ感応度 — 業者のレート精度・実質スプレッドがエッジを消す様子

使い方:  python3 run_s15_analysis.py [PAIR ...]   （既定 EURJPY USDJPY）
"""
import sys
from datetime import datetime

from backtest.data import load_csv
from backtest.engine import run_backtest
from backtest.strategies import STRATEGIES

PAYOUT = 2.05
BE = 100.0 / PAYOUT  # 損益分岐勝率 48.78%


def signed_moves(series, signals):
    """シグナルバー終値→ちょうど15秒後の終値の、方向に沿った符号付き変化。"""
    bars = series.bars
    moves = []
    for i in range(len(bars) - 1):
        d = signals[i]
        if d is None:
            continue
        t0 = datetime.fromisoformat(bars[i].time)
        t1 = datetime.fromisoformat(bars[i + 1].time)
        if (t1 - t0).total_seconds() != 15:
            continue
        mv = bars[i + 1].close - bars[i].close
        moves.append(mv if d == "UP" else -mv)
    return moves


def analyze(pair: str) -> None:
    s = load_csv(f"data/s15/{pair}.csv.gz", name=pair)
    bars = s.bars
    deltas = []
    for i in range(len(bars) - 1):
        t0 = datetime.fromisoformat(bars[i].time)
        t1 = datetime.fromisoformat(bars[i + 1].time)
        if (t1 - t0).total_seconds() == 15:
            deltas.append(bars[i + 1].close - bars[i].close)
    n = len(deltas)
    tie_raw = sum(1 for d in deltas if d == 0) / n
    tie_3dp = sum(1 for d in deltas if round(abs(d), 3) < 0.0005) / n
    med = sorted(abs(d) for d in deltas)[n // 2]

    print(f"\n===== {pair} (15秒足 {len(bars):,} 本) =====")
    print(f"同値率: 生ミッド {tie_raw*100:.2f}% / 0.001丸め {tie_3dp*100:.2f}%"
          f"（損益分岐が成立する上限は 2.44%）")
    print(f"15秒|Δ|中央値: {med:.5f}（JPYペアで {med*100:.2f} pips）")
    print("ランダム方向のEV（同値=負け, エントリーレートへの不利マークアップ s 込み）:")
    for mk in (0.0, 0.001, 0.002):
        pw = sum(1 for d in deltas if abs(d) > mk) / n / 2
        ev = pw * (PAYOUT - 1) * 1000 - (1 - pw) * 1000
        print(f"  s={mk:.3f}: P(勝)={pw*100:5.2f}%  EV {ev:+5.0f}円/1000円")

    print(f"戦略成績（摩擦ゼロのミッド, expiry=15秒, payout={PAYOUT}, 同値=負け）:")
    for name in ("random", "bollinger", "rsi", "ma_cross", "macd"):
        fn = STRATEGIES[name]
        sig = fn(s, seed=0) if name == "random" else fn(s)
        r = run_backtest(s, sig, payout=PAYOUT, expiry_bars=1, stake=1000,
                         start_balance=100000, tie_policy="loss",
                         no_overlap=True, name=name)
        tot = len(r.trades)
        if tot == 0:
            print(f"  {name:10s} 取引なし")
            continue
        wins = sum(1 for t in r.trades if t.result == "win")
        pnl = sum(t.pnl for t in r.trades)
        wr = wins / tot * 100
        print(f"  {name:10s} {tot:6d}回  勝率 {wr:5.2f}%  edge {wr-BE:+5.2f}pt"
              f"  損益 {pnl:+,.0f}円")

    print("bollinger の摩擦感応度（判定丸め・マークアップ）:")
    moves = signed_moves(s, STRATEGIES["bollinger"](s))
    m = len(moves)

    def row(label, wins):
        wr = wins / m * 100
        ev = wins / m * (PAYOUT - 1) * 1000 - (1 - wins / m) * 1000
        print(f"  {label:28s} 勝率 {wr:5.2f}%  edge {wr-BE:+6.2f}pt  EV {ev:+5.0f}円")

    row("摩擦ゼロ(ミッド)", sum(1 for x in moves if x > 0))
    row("0.001丸め判定", sum(1 for x in moves if round(x, 3) > 0))
    for mk in (0.001, 0.002, 0.003):
        row(f"マークアップ {mk*100:.1f}pips", sum(1 for x in moves if x > mk))


def main() -> int:
    pairs = [a.upper() for a in sys.argv[1:]] or ["EURJPY", "USDJPY"]
    print(f"ペイアウト {PAYOUT} → 損益分岐勝率 {BE:.2f}%（50%未満に見えるのがミソ）")
    for p in pairs:
        analyze(p)
    print("""
【読み方 — 正直な結論】
* 同値=負けの15秒取引では、同値率が2.44%を超えた時点でコイン投げは負ける。
  実測の同値率はその2〜8倍あり、2.05倍の「見かけの優位」はここで消える。
* ミッド価格で出る戦略の見かけのエッジは、業者の表示精度(0.001)への丸めや
  0.1pips程度の実質マークアップでゼロ〜マイナスに落ちる。15秒の値動きの
  中央値がそもそも0.2〜0.35pipsしかないため、微小な摩擦が支配的。
* つまり高ペイアウトは「同値と判定レートの摩擦」で回収されている。""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
