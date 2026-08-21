"""
再利用可能な検証コア(Claude Code はこれを import してループを書く)
=================================================================
鉄の掟(絶対に外すな。外した瞬間このプロジェクトは意味を失う):
  1. 1エントリー = 1ポジション。マーチン/ナンピン禁止。
  2. 損切りは固定。必ず入る。
  3. スプレッド(コスト)を必ず引く。盛らない。
  4. 判定は out-of-sample(未来データ)で行う。前半で作って後半で答え合わせ。
  5. さらに3分割で全区間プラスを要求(まぐれ排除)。

【最重要警告 / カーブフィッティング】
  組み合わせを増やせば「生存者」は必ず出る。それは勝てる型が
  見つかったのではなく、数を撃った結果の "まぐれ当たり" が
  統計的に紛れ込んだだけの可能性が高い。
  ループで大量に回すほど、この偽陽性は増える。
  → 生存者が出たら「勝った」と思うな。まず疑え。
  → 検証方法は本ファイル末尾の validate_survivor() を必ず通せ。
"""
import pandas as pd, numpy as np, os

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

PIP_MAP = {'USDJPY':0.01,'EURJPY':0.01,'GBPJPY':0.01,'XAUUSD':0.1}
# HFM実勢の保守的スプレッド(pips)。実口座の値に更新するのが望ましい。
SPR_MAP = {'EURUSD':1.2,'GBPUSD':1.5,'USDJPY':1.3,'AUDUSD':1.4,'USDCHF':1.6,
           'USDCAD':1.7,'EURJPY':1.8,'GBPJPY':2.2,'EURGBP':1.6,'XAUUSD':20.0}

def load(pair):
    df = pd.read_csv(os.path.join(DATA_DIR, f'{pair}.csv'))
    o = (df['open']/100000).values
    h = (df['high']/100000).values
    l = (df['low']/100000).values
    c = (df['close']/100000).values
    return o, h, l, c

def indicators(c, h, l, fast, slow, rsi_p=14, bb_p=20):
    mf = pd.Series(c).rolling(fast).mean().values
    ms = pd.Series(c).rolling(slow).mean().values
    d = pd.Series(c).diff()
    g = d.clip(lower=0).rolling(rsi_p).mean()
    ls = (-d.clip(upper=0)).rolling(rsi_p).mean()
    rs = g/ls.replace(0, np.nan)
    rsi = (100 - 100/(1+rs)).values
    hh = pd.Series(h).rolling(slow).max().values
    ll = pd.Series(l).rolling(slow).min().values
    m = pd.Series(c).rolling(bb_p).mean(); sd = pd.Series(c).rolling(bb_p).std()
    bb_up = (m+2*sd).values; bb_dn = (m-2*sd).values
    atr = pd.Series(h-l).rolling(14).mean().values
    return dict(mf=mf, ms=ms, rsi=rsi, hh=hh, ll=ll, bb_up=bb_up, bb_dn=bb_dn, atr=atr)

# --- シグナル生成器。新しい型を試すならここに関数を足す ---
def signal(logic, ix, i, c):
    mf,ms,rsi,hh,ll = ix['mf'],ix['ms'],ix['rsi'],ix['hh'],ix['ll']
    bbu,bbd = ix['bb_up'],ix['bb_dn']
    if logic=='trend':
        if mf[i-1]<=ms[i-1] and mf[i]>ms[i]: return 1
        if mf[i-1]>=ms[i-1] and mf[i]<ms[i]: return -1
    elif logic=='revert_rsi':
        if rsi[i]<30: return 1
        if rsi[i]>70: return -1
    elif logic=='revert_bb':
        if c[i]<bbd[i]: return 1
        if c[i]>bbu[i]: return -1
    elif logic=='breakout':
        if c[i-1]<hh[i-1] and c[i]>=hh[i-1]: return 1
        if c[i-1]>ll[i-1] and c[i]<=ll[i-1]: return -1
    elif logic=='pullback':
        up = mf[i]>ms[i]
        if up and rsi[i]<40: return 1
        if (not up) and rsi[i]>60: return -1
    elif logic=='trend_rsi':
        if mf[i]>ms[i] and 40<rsi[i]<60: return 1
        if mf[i]<ms[i] and 40<rsi[i]<60: return -1
    return 0

def backtest(logic, prm, pair, lo_i=None, hi_i=None):
    """prm=(fast,slow,rsi_p,sl_pips,tp_pips,bb_p)。区間 [lo_i,hi_i) で検証。"""
    fast,slow,rsi_p,sl,tp,bb_p = prm
    o,h,l,c = load(pair)
    ix = indicators(c,h,l,fast,slow,rsi_p,bb_p)
    pip = PIP_MAP.get(pair,0.0001); sp = SPR_MAP[pair]*pip
    n = len(c)
    lo_i = max(slow+2, bb_p+2) if lo_i is None else max(lo_i, slow+2, bb_p+2)
    hi_i = n if hi_i is None else hi_i
    trades=[]; pos=None
    for i in range(lo_i, hi_i):
        if pos:
            d,e,s,t = pos
            if d==1:
                if l[i]<=s: trades.append((s-e)-sp); pos=None
                elif h[i]>=t: trades.append((t-e)-sp); pos=None
            else:
                if h[i]>=s: trades.append((e-s)-sp); pos=None
                elif l[i]<=t: trades.append((e-t)-sp); pos=None
        if pos: continue
        sig = signal(logic, ix, i, c)
        if sig==1: e=c[i]; pos=(1,e,e-sl*pip,e+tp*pip)
        elif sig==-1: e=c[i]; pos=(-1,e,e+sl*pip,e-tp*pip)
    tr = np.array(trades)
    if len(tr)<40: return None
    w=tr[tr>0]; ls=tr[tr<=0]
    pf = w.sum()/abs(ls.sum()) if ls.sum()!=0 else 99
    eq = np.cumsum(tr); peak=np.maximum.accumulate(eq); maxdd=(peak-eq).max()
    return dict(n=len(tr), wr=len(w)/len(tr)*100, pf=pf,
                exp=tr.mean()/pip, maxdd=maxdd/pip, total=eq[-1]/pip)

def validate_survivor(logic, prm, pair):
    """まぐれ排除の最終関門。ここを通らない候補は捨てる。"""
    o,h,l,c = load(pair); n=len(c); split=int(n*0.6)
    ins = backtest(logic,prm,pair,0,split)
    out = backtest(logic,prm,pair,split,n)
    if not ins or not out: return False,{}
    # 3分割 全区間プラス
    a,b = int(n/3),int(2*n/3)
    seg_ok = True
    for lo_i,hi_i in [(0,a),(a,b),(b,n)]:
        r = backtest(logic,prm,pair,lo_i,hi_i)
        if not r or r['exp']<=0: seg_ok=False; break
    passed = (ins['pf']>=1.25 and ins['exp']>0 and
              out['pf']>=1.3 and out['exp']>0 and out['n']>=80 and seg_ok)
    return passed, dict(in_sample=ins, out_sample=out)

# 既知の型リスト(順張り/逆張り両方)
LOGICS = ['trend','revert_rsi','revert_bb','breakout','pullback','trend_rsi']
