"""
ひなさん専用 バックテストエンジン v1
鉄の掟(コードに強制):
  - マーチン/ナンピン 完全禁止(1エントリー1ポジション)
  - 損切り 固定(必ず入る)
  - 全指標を記録(PF, 最大DD, 勝率, トレード数, 期待値)
  - スプレッド/コストを引く(盛らない)
"""
import pandas as pd
import numpy as np

df = pd.read_csv('eurusd_h1.csv')
df['price_close'] = df['close'] / 100000.0
df['price_open']  = df['open']  / 100000.0
df['price_high']  = df['high']  / 100000.0
df['price_low']   = df['low']   / 100000.0
df = df.reset_index(drop=True)

SPREAD = 0.00012   # 1.2 pips 実際のコスト(盛らないため必ず引く)
PIP = 0.0001

def run(logic, sl_pips, tp_pips, fast=20, slow=50, rsi_period=14):
    """1トレード1ポジション。損切り固定。マーチンなし。"""
    close = df['price_close'].values
    high  = df['price_high'].values
    low   = df['price_low'].values

    # 指標
    ma_fast = pd.Series(close).rolling(fast).mean().values
    ma_slow = pd.Series(close).rolling(slow).mean().values
    delta = pd.Series(close).diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = (100 - 100/(1+rs)).values

    trades = []
    pos = None  # (dir, entry, sl, tp)
    for i in range(slow+1, len(close)):
        # 決済判定(保有中)
        if pos:
            d, entry, sl, tp = pos
            if d == 1:  # buy
                if low[i] <= sl:   trades.append((sl-entry)-SPREAD); pos=None
                elif high[i] >= tp:trades.append((tp-entry)-SPREAD); pos=None
            else:       # sell
                if high[i] >= sl:  trades.append((entry-sl)-SPREAD); pos=None
                elif low[i] <= tp: trades.append((entry-tp)-SPREAD); pos=None
        if pos: continue

        # エントリー判定
        sig = 0
        if logic == 'trend':   # 順張り:GC買い/DC売り
            if ma_fast[i-1] <= ma_slow[i-1] and ma_fast[i] > ma_slow[i]:  sig=1
            elif ma_fast[i-1] >= ma_slow[i-1] and ma_fast[i] < ma_slow[i]: sig=-1
        elif logic == 'revert': # 逆張り:RSI売られすぎ買い/買われすぎ売り
            if rsi[i] < 30:  sig=1
            elif rsi[i] > 70: sig=-1

        if sig == 1:
            e=close[i]; pos=(1, e, e-sl_pips*PIP, e+tp_pips*PIP)
        elif sig == -1:
            e=close[i]; pos=(-1, e, e+sl_pips*PIP, e-tp_pips*PIP)

    return np.array(trades)

def stats(trades, name):
    if len(trades)==0:
        print(f"{name}: トレード0"); return
    wins = trades[trades>0]; losses = trades[trades<=0]
    pf = wins.sum()/abs(losses.sum()) if losses.sum()!=0 else float('inf')
    winrate = len(wins)/len(trades)*100
    # 資産曲線と最大DD
    eq = np.cumsum(trades)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq)
    maxdd = dd.max()
    exp = trades.mean()  # 1トレード期待値(pips換算 = *10000)
    print(f"\n===== {name} =====")
    print(f"総トレード数: {len(trades)}")
    print(f"勝率        : {winrate:.1f}%")
    print(f"PF(利益係数): {pf:.2f}   {'✅' if pf>=1.3 else '❌ 掟PF1.3未達'}")
    print(f"期待値/回   : {exp*10000:+.2f} pips  {'✅' if exp>0 else '❌ 負け越し'}")
    print(f"最大DD      : {maxdd*10000:.1f} pips")
    print(f"総損益      : {eq[-1]*10000:+.1f} pips")

for logic,label in [('trend','順張り(MA GC/DC)'),('revert','逆張り(RSI 30/70)')]:
    # 損切り20pips / 利確40pips(リスクリワード1:2)を素の初期値に
    t = run(logic, sl_pips=20, tp_pips=40)
    stats(t, label)
