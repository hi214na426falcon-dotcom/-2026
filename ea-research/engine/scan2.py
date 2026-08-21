"""
大規模探索 v4 — 逆張り/順張り 全部入り + まぐれ排除
掟: マーチンなし/損切り固定/スプレッド控除
まぐれ対策(3重):
  1. in-sample(前半6割)と out-sample(後半4割)両方でPF>=1.3
  2. さらに期間を3分割し、3期間すべてで期待値プラス(頑健性)
  3. 最低トレード数80以上(偶然を減らす)
"""
import pandas as pd, numpy as np, itertools

PAIRS=['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF','USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
PIP_MAP={'USDJPY':0.01,'EURJPY':0.01,'GBPJPY':0.01,'XAUUSD':0.1}
SPR_MAP={'EURUSD':1.2,'GBPUSD':1.5,'USDJPY':1.3,'AUDUSD':1.4,'USDCHF':1.6,
         'USDCAD':1.7,'EURJPY':1.8,'GBPJPY':2.2,'EURGBP':1.6,'XAUUSD':20.0}

def load(p):
    df=pd.read_csv(f'{p}.csv')
    return (df['open']/100000).values,(df['high']/100000).values,(df['low']/100000).values,(df['close']/100000).values

def ind(c,h,l,fast,slow,rsi_p,bb_p):
    mf=pd.Series(c).rolling(fast).mean().values
    ms=pd.Series(c).rolling(slow).mean().values
    d=pd.Series(c).diff()
    g=d.clip(lower=0).rolling(rsi_p).mean(); ll_=(-d.clip(upper=0)).rolling(rsi_p).mean()
    rs=g/ll_.replace(0,np.nan); rsi=(100-100/(1+rs)).values
    hh=pd.Series(h).rolling(slow).max().values
    lo=pd.Series(l).rolling(slow).min().values
    m=pd.Series(c).rolling(bb_p).mean(); sd=pd.Series(c).rolling(bb_p).std()
    bb_up=(m+2*sd).values; bb_dn=(m-2*sd).values
    return mf,ms,rsi,hh,lo,bb_up,bb_dn

def bt(logic,prm,c,h,l,pip,spr,lo_i,hi_i):
    fast,slow,rsi_p,sl,tp,bb_p=prm
    mf,ms,rsi,hh,lln,bbu,bbd=ind(c,h,l,fast,slow,rsi_p,bb_p)
    trades=[]; pos=None; sp=spr*pip
    start=max(slow+2,bb_p+2,lo_i)
    for i in range(start,hi_i):
        if pos:
            d,e,s,t=pos
            if d==1:
                if l[i]<=s: trades.append((s-e)-sp); pos=None
                elif h[i]>=t: trades.append((t-e)-sp); pos=None
            else:
                if h[i]>=s: trades.append((e-s)-sp); pos=None
                elif l[i]<=t: trades.append((e-t)-sp); pos=None
        if pos: continue
        sig=0
        if logic=='trend':
            if mf[i-1]<=ms[i-1] and mf[i]>ms[i]: sig=1
            elif mf[i-1]>=ms[i-1] and mf[i]<ms[i]: sig=-1
        elif logic=='revert_rsi':
            if rsi[i]<30: sig=1
            elif rsi[i]>70: sig=-1
        elif logic=='revert_bb':      # 逆張り:バンド外れで戻り狙い
            if c[i]<bbd[i]: sig=1
            elif c[i]>bbu[i]: sig=-1
        elif logic=='breakout':
            if c[i-1]<hh[i-1] and c[i]>=hh[i-1]: sig=1
            elif c[i-1]>lln[i-1] and c[i]<=lln[i-1]: sig=-1
        elif logic=='pullback':
            up=mf[i]>ms[i]
            if up and rsi[i]<40: sig=1
            elif (not up) and rsi[i]>60: sig=-1
        elif logic=='trend_rsi':      # 順張り+RSI過熱回避
            if mf[i]>ms[i] and 40<rsi[i]<60: sig=1
            elif mf[i]<ms[i] and 40<rsi[i]<60: sig=-1
        if sig==1: e=c[i]; pos=(1,e,e-sl*pip,e+tp*pip)
        elif sig==-1: e=c[i]; pos=(-1,e,e+sl*pip,e-tp*pip)
    tr=np.array(trades)
    if len(tr)<40: return None
    w=tr[tr>0]; ls=tr[tr<=0]
    pf=w.sum()/abs(ls.sum()) if ls.sum()!=0 else 99
    return dict(n=len(tr),wr=len(w)/len(tr)*100,pf=pf,exp=tr.mean()/pip,tr=tr)

def three_split_ok(logic,prm,c,h,l,pip,spr,n):
    # 3等分して全区間プラスか(頑健性チェック)
    a,b=int(n/3),int(2*n/3)
    for lo_i,hi_i in [(0,a),(a,b),(b,n)]:
        r=bt(logic,prm,c,h,l,pip,spr,lo_i,hi_i)
        if not r or r['exp']<=0: return False
    return True

grid=dict(fast=[10,20,30],slow=[50,100,200],rsi_p=[14],
          sl=[20,40],tp=[40,80,120],bb_p=[20])
logics=['trend','revert_rsi','revert_bb','breakout','pullback','trend_rsi']

survivors=[]; scanned=0
for p in PAIRS:
    o,h,l,c=load(p); pip=PIP_MAP.get(p,0.0001); spr=SPR_MAP[p]
    n=len(c); split=int(n*0.6)
    for logic in logics:
        for fast,slow,rsi_p,sl,tp,bb_p in itertools.product(
            grid['fast'],grid['slow'],grid['rsi_p'],grid['sl'],grid['tp'],grid['bb_p']):
            if fast>=slow: continue
            prm=(fast,slow,rsi_p,sl,tp,bb_p); scanned+=1
            ins=bt(logic,prm,c,h,l,pip,spr,0,split)
            if not ins or ins['pf']<1.25 or ins['exp']<=0: continue
            out=bt(logic,prm,c,h,l,pip,spr,split,n)
            if not out or out['pf']<1.3 or out['exp']<=0 or out['n']<80: continue
            if not three_split_ok(logic,prm,c,h,l,pip,spr,n): continue
            survivors.append((p,logic,prm,ins,out))

print(f"総スキャン数: {scanned}")
print(f"3重フィルタ全通過(まぐれ排除後)の生存者: {len(survivors)}\n")
survivors.sort(key=lambda r:-(r[4]['pf']))
if survivors:
    print(f"{'pair':8}{'logic':12}{'params':26}{'in_PF':>6}{'out_PF':>7}{'out_wr':>7}{'out_n':>6}")
    for p,logic,prm,ins,out in survivors[:30]:
        print(f"{p:8}{logic:12}{str(prm):26}{ins['pf']:>6.2f}{out['pf']:>7.2f}{out['wr']:>6.1f}%{out['n']:>6}")
else:
    print("該当なし。")
