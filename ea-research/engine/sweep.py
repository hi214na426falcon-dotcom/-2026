"""
ひなさん専用 パラメータ探索 v2
目的: 「全組み合わせ」は不可能なので、代表的な型を横断で回し
     構造的に勝てない型を除外し、わずかでもエッジのある型を炙り出す。
     カーブフィット防止のため in-sample / out-of-sample で分割検証。
"""
import pandas as pd, numpy as np, itertools

df = pd.read_csv('eurusd_h1.csv')
for c in ['open','high','low','close']:
    df['p_'+c] = df[c]/100000.0
df = df.reset_index(drop=True)
n = len(df)
split = int(n*0.6)  # 前半60%で探索、後半40%で答え合わせ(未来を覗かない)

SPREAD=0.00012; PIP=0.0001
close=df['p_close'].values; high=df['p_high'].values; low=df['p_low'].values

def indicators(fast,slow,rsi_p):
    mf=pd.Series(close).rolling(fast).mean().values
    ms=pd.Series(close).rolling(slow).mean().values
    d=pd.Series(close).diff()
    g=d.clip(lower=0).rolling(rsi_p).mean(); l=(-d.clip(upper=0)).rolling(rsi_p).mean()
    rs=g/l.replace(0,np.nan); rsi=(100-100/(1+rs)).values
    atr=pd.Series(high-low).rolling(14).mean().values
    return mf,ms,rsi,atr

def backtest(logic, params, lo, hi):
    fast,slow,rsi_p,sl,tp,use_filter = params
    mf,ms,rsi,atr = indicators(fast,slow,rsi_p)
    atr_med = np.nanmedian(atr[lo:hi])
    trades=[]; pos=None
    start=max(slow+1, lo)
    for i in range(start, hi):
        if pos:
            d,e,s,t=pos
            if d==1:
                if low[i]<=s: trades.append((s-e)-SPREAD); pos=None
                elif high[i]>=t: trades.append((t-e)-SPREAD); pos=None
            else:
                if high[i]>=s: trades.append((e-s)-SPREAD); pos=None
                elif low[i]<=t: trades.append((e-t)-SPREAD); pos=None
        if pos: continue
        # トレンド強度フィルター(ONなら、値動きが大きい時だけ)
        if use_filter and not (atr[i] > atr_med): continue
        sig=0
        if logic=='trend':
            if mf[i-1]<=ms[i-1] and mf[i]>ms[i]: sig=1
            elif mf[i-1]>=ms[i-1] and mf[i]<ms[i]: sig=-1
        elif logic=='revert':
            if rsi[i]<30: sig=1
            elif rsi[i]>70: sig=-1
        elif logic=='trend_pullback':  # 順張り+押し目:上昇トレンド中にRSI低下で買い
            up = mf[i]>ms[i]
            if up and rsi[i]<40: sig=1
            elif (not up) and rsi[i]>60: sig=-1
        if sig==1: e=close[i]; pos=(1,e,e-sl*PIP,e+tp*PIP)
        elif sig==-1: e=close[i]; pos=(-1,e,e+sl*PIP,e-tp*PIP)
    tr=np.array(trades)
    if len(tr)<30: return None
    wins=tr[tr>0]; losses=tr[tr<=0]
    pf=wins.sum()/abs(losses.sum()) if losses.sum()!=0 else 99
    return dict(n=len(tr), wr=len(wins)/len(tr)*100, pf=pf,
                exp=tr.mean()*10000, total=tr.sum()*10000)

# 探索する型(全網羅でなく、意味のある代表値だけ = 理屈で刈り込み)
grid = {
  'fast':[10,20], 'slow':[50,100], 'rsi_p':[14],
  'sl':[20,30,50], 'tp':[20,40,60,100], 'filt':[False,True]
}
logics=['trend','revert','trend_pullback']

results=[]
for logic in logics:
    for fast,slow,rsi_p,sl,tp,filt in itertools.product(
        grid['fast'],grid['slow'],grid['rsi_p'],grid['sl'],grid['tp'],grid['filt']):
        if fast>=slow: continue
        p=(fast,slow,rsi_p,sl,tp,filt)
        ins=backtest(logic,p,split,n)      # 探索は「前半」… いや後半を探索に使い
        # in-sample = 前半(0..split), out-sample = 後半(split..n)
        ins=backtest(logic,p,slow+1,split)
        if not ins: continue
        results.append((logic,p,ins))

# in-sampleでPF>1.15 のものだけ通す(ゆるめの足切り)
cand=[r for r in results if r[2]['pf']>1.15 and r[2]['exp']>0]
cand.sort(key=lambda r:-r[2]['pf'])
print(f"探索した組合せ: {len(results)}  /  前半でエッジありの候補: {len(cand)}")
print("\n--- 前半(in-sample)で有望だった上位、後半(未来)で答え合わせ ---")
print(f"{'logic':16}{'params':28}{'in_PF':>7}{'out_PF':>8}{'out_exp':>9}{'out_n':>7}")
survivors=[]
for logic,p,ins in cand[:15]:
    out=backtest(logic,p,split,n)
    if not out: continue
    tag='  <<生存' if out['pf']>=1.3 and out['exp']>0 else ''
    if out['pf']>=1.3 and out['exp']>0: survivors.append((logic,p,ins,out))
    print(f"{logic:16}{str(p):28}{ins['pf']:>7.2f}{out['pf']:>8.2f}{out['exp']:>9.2f}{out['n']:>7}{tag}")

print(f"\n前半・後半 両方でPF1.3超え(本物候補): {len(survivors)}件")
