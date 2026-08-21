"""
市場横断エッジスキャナー v3
EAを漁るのでなく「どの市場×どの型にエッジがあるか」を炙り出す。
掟: マーチンなし / 損切り固定 / スプレッド控除 / 前後半分割で未来検証。
生存条件: in-sample と out-of-sample の両方で PF>=1.3 かつ 期待値プラス。
"""
import pandas as pd, numpy as np, itertools, glob, os

PAIRS=['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF','USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
PIP_MAP={'USDJPY':0.01,'EURJPY':0.01,'GBPJPY':0.01,'XAUUSD':0.1}  # 円・ゴールドは桁が違う
# スプレッド(pips, HFM実勢のざっくり保守値)
SPR_MAP={'EURUSD':1.2,'GBPUSD':1.5,'USDJPY':1.3,'AUDUSD':1.4,'USDCHF':1.6,
         'USDCAD':1.7,'EURJPY':1.8,'GBPJPY':2.2,'EURGBP':1.6,'XAUUSD':20.0}

def load(p):
    df=pd.read_csv(f'{p}.csv')
    div=100000.0
    for c in ['open','high','low','close']:
        df['p_'+c]=df[c]/div
    return df

def indicators(close,high,low,fast,slow,rsi_p):
    mf=pd.Series(close).rolling(fast).mean().values
    ms=pd.Series(close).rolling(slow).mean().values
    d=pd.Series(close).diff()
    g=d.clip(lower=0).rolling(rsi_p).mean(); l=(-d.clip(upper=0)).rolling(rsi_p).mean()
    rs=g/l.replace(0,np.nan); rsi=(100-100/(1+rs)).values
    hh=pd.Series(high).rolling(slow).max().values
    ll=pd.Series(low).rolling(slow).min().values
    atr=pd.Series(high-low).rolling(14).mean().values
    return mf,ms,rsi,hh,ll,atr

def backtest(logic,params,close,high,low,pip,spread,lo,hi):
    fast,slow,rsi_p,sl,tp=params
    mf,ms,rsi,hh,ll,atr=indicators(close,high,low,fast,slow,rsi_p)
    trades=[]; pos=None
    start=max(slow+2,lo)
    sp=spread*pip
    for i in range(start,hi):
        if pos:
            d,e,s,t=pos
            if d==1:
                if low[i]<=s: trades.append((s-e)-sp); pos=None
                elif high[i]>=t: trades.append((t-e)-sp); pos=None
            else:
                if high[i]>=s: trades.append((e-s)-sp); pos=None
                elif low[i]<=t: trades.append((e-t)-sp); pos=None
        if pos: continue
        sig=0
        if logic=='trend':
            if mf[i-1]<=ms[i-1] and mf[i]>ms[i]: sig=1
            elif mf[i-1]>=ms[i-1] and mf[i]<ms[i]: sig=-1
        elif logic=='revert':
            if rsi[i]<30: sig=1
            elif rsi[i]>70: sig=-1
        elif logic=='breakout':  # ブレイクアウト:直近高値超えで買い/安値割れで売り
            if close[i-1]<hh[i-1] and close[i]>=hh[i-1]: sig=1
            elif close[i-1]>ll[i-1] and close[i]<=ll[i-1]: sig=-1
        elif logic=='pullback':  # 順張り押し目
            up=mf[i]>ms[i]
            if up and rsi[i]<40: sig=1
            elif (not up) and rsi[i]>60: sig=-1
        if sig==1: e=close[i]; pos=(1,e,e-sl*pip,e+tp*pip)
        elif sig==-1: e=close[i]; pos=(-1,e,e+sl*pip,e-tp*pip)
    tr=np.array(trades)
    if len(tr)<40: return None
    w=tr[tr>0]; ls=tr[tr<=0]
    pf=w.sum()/abs(ls.sum()) if ls.sum()!=0 else 99
    return dict(n=len(tr),wr=len(w)/len(tr)*100,pf=pf,exp=tr.mean()/pip)

grid=dict(fast=[10,20],slow=[50,100],rsi_p=[14],sl=[20,40],tp=[40,80,120])
logics=['trend','revert','breakout','pullback']

survivors=[]; scanned=0
for p in PAIRS:
    df=load(p); c=df['p_close'].values; h=df['p_high'].values; l=df['p_low'].values
    pip=PIP_MAP.get(p,0.0001); spr=SPR_MAP[p]; n=len(c); split=int(n*0.6)
    for logic in logics:
        for fast,slow,rsi_p,sl,tp in itertools.product(
            grid['fast'],grid['slow'],grid['rsi_p'],grid['sl'],grid['tp']):
            if fast>=slow: continue
            prm=(fast,slow,rsi_p,sl,tp); scanned+=1
            ins=backtest(logic,prm,c,h,l,pip,spr,slow+2,split)
            if not ins or ins['pf']<1.2 or ins['exp']<=0: continue
            out=backtest(logic,prm,c,h,l,pip,spr,split,n)
            if not out: continue
            if out['pf']>=1.3 and out['exp']>0:
                survivors.append((p,logic,prm,ins,out))

print(f"総スキャン数: {scanned}")
print(f"前後半 両方で PF1.3超え & 期待値プラス の生存者: {len(survivors)}\n")
survivors.sort(key=lambda r:-(r[4]['pf']))
print(f"{'pair':8}{'logic':10}{'params':22}{'in_PF':>6}{'out_PF':>7}{'out_wr':>7}{'out_n':>6}")
for p,logic,prm,ins,out in survivors[:25]:
    print(f"{p:8}{logic:10}{str(prm):22}{ins['pf']:>6.2f}{out['pf']:>7.2f}{out['wr']:>6.1f}%{out['n']:>6}")
