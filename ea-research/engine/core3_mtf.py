"""
真の複数時間足(MTF)エンジン — READMEの本命階層
====================================================
H1 のトレンド方向にだけ、M15 でエントリー。鉄の掟は core と同じ:
  1エントリー1ポジション / 損切り固定必ず入る / スプレッド控除 /
  out-of-sample(M15インデックスの前6割で作り後4割で答え合わせ)/ 3分割全区間プラス。

★ルックアヘッド厳禁: H1トレンドは「そのH1足が確定した後」のM15足でだけ参照する。
  実装は merge_asof で H1 を確定時刻(+1h)にずらして後方結合。未来を絶対に見ない。
"""
import pandas as pd, numpy as np, os
import core

_M15 = {}
def load_m15(pair):
    if pair in _M15: return _M15[pair]
    df = pd.read_csv(os.path.join(core.DATA_DIR, f'{pair}_m15.csv'))
    df['t'] = pd.to_datetime(df['Date'])
    for k in ('open','high','low','close'): df[k] = df[k]/100000
    _M15[pair] = df
    return df

_MTFIX = {}
def _mtf_frame(pair, h1_fast, h1_slow, m_fast, m_slow, rsi_p):
    """M15足に、確定済みH1トレンドと、M15側の指標を貼り付けた配列群を返す。"""
    key = (pair, h1_fast, h1_slow, m_fast, m_slow, rsi_p)
    if key in _MTFIX: return _MTFIX[key]
    # --- H1 トレンド ---
    h1 = pd.read_csv(os.path.join(core.DATA_DIR, f'{pair}.csv'))
    h1['t'] = pd.to_datetime(h1['Date']); hc = h1['close']/100000
    hf = hc.rolling(h1_fast).mean(); hs = hc.rolling(h1_slow).mean()
    h1trend = np.where(hf > hs, 1, np.where(hf < hs, -1, 0))
    # H1足は確定してから有効 → タイムスタンプを +1h ずらす(open時刻+1h=close時刻)
    h1v = pd.DataFrame({'t': h1['t'] + pd.Timedelta(hours=1), 'h1trend': h1trend}).dropna()
    # --- M15 指標 ---
    m = load_m15(pair).copy()
    c = m['close']
    m['mf'] = c.rolling(m_fast).mean(); m['ms'] = c.rolling(m_slow).mean()
    d = c.diff(); g = d.clip(lower=0).rolling(rsi_p).mean()
    ls = (-d.clip(upper=0)).rolling(rsi_p).mean()
    rs = g/ls.replace(0, np.nan); m['rsi'] = 100 - 100/(1+rs)
    hh = m['high'].rolling(m_slow).max(); ll = m['low'].rolling(m_slow).min()
    m['hh'] = hh.shift(1); m['ll'] = ll.shift(1)
    # 後方結合(未来を見ない): 各M15足に、その時刻までに確定した最新H1トレンド
    m = pd.merge_asof(m.sort_values('t'), h1v.sort_values('t'), on='t', direction='backward')
    out = dict(o=m['open'].values, h=m['high'].values, l=m['low'].values,
               c=m['close'].values, mf=m['mf'].values, ms=m['ms'].values,
               rsi=m['rsi'].values, hh=m['hh'].values, ll=m['ll'].values,
               h1trend=m['h1trend'].fillna(0).values)
    _MTFIX[key] = out
    return out

def _m15_signal(trig, ix, i):
    """M15側のエントリートリガ。H1方向フィルタは呼び出し側で当てる。"""
    mf,ms,rsi,hh,ll,c = ix['mf'],ix['ms'],ix['rsi'],ix['hh'],ix['ll'],ix['c']
    if trig == 'cross':
        if mf[i-1] <= ms[i-1] and mf[i] > ms[i]: return 1
        if mf[i-1] >= ms[i-1] and mf[i] < ms[i]: return -1
    elif trig == 'pull':      # 押し目/戻り(RSIの行き過ぎ)
        if rsi[i] < 35: return 1
        if rsi[i] > 65: return -1
    elif trig == 'break':     # 直近高安ブレイク
        if c[i] >= hh[i]: return 1
        if c[i] <= ll[i]: return -1
    return 0

def backtest_mtf(pair, h1_fast, h1_slow, m_fast, m_slow, trig, sl, tp,
                 rsi_p=14, lo_i=None, hi_i=None):
    ix = _mtf_frame(pair, h1_fast, h1_slow, m_fast, m_slow, rsi_p)
    o,h,l,c = ix['o'],ix['h'],ix['l'],ix['c']; tr_h1 = ix['h1trend']
    pip = core.PIP_MAP.get(pair, 0.0001); sp = core.SPR_MAP[pair]*pip
    n = len(c)
    floor = max(h1_slow*4 + 5, m_slow + 5, 30)  # H1のslow本ぶん(M15換算×4)は暖機
    lo_i = floor if lo_i is None else max(lo_i, floor)
    hi_i = n if hi_i is None else hi_i
    trades = []; pos = None
    for i in range(lo_i, hi_i):
        if pos:
            d,e,s,t = pos
            if d == 1:
                if l[i] <= s: trades.append((s-e)-sp); pos=None
                elif h[i] >= t: trades.append((t-e)-sp); pos=None
            else:
                if h[i] >= s: trades.append((e-s)-sp); pos=None
                elif l[i] <= t: trades.append((e-t)-sp); pos=None
        if pos: continue
        reg = tr_h1[i]
        if reg == 0: continue
        sig = _m15_signal(trig, ix, i)
        if sig == 0 or sig != reg: continue   # H1トレンドと一致するM15シグナルだけ
        e = c[i]
        if sig == 1: pos = (1, e, e-sl*pip, e+tp*pip)
        else:        pos = (-1, e, e+sl*pip, e-tp*pip)
    tr = np.array(trades)
    if len(tr) < 40: return None
    w = tr[tr>0]; lsr = tr[tr<=0]
    pf = w.sum()/abs(lsr.sum()) if lsr.sum()!=0 else 99
    eq = np.cumsum(tr); peak=np.maximum.accumulate(eq); maxdd=(peak-eq).max()
    return dict(n=len(tr), wr=len(w)/len(tr)*100, pf=pf,
                exp=tr.mean()/pip, maxdd=maxdd/pip, total=eq[-1]/pip)

def validate_mtf(pair, h1_fast, h1_slow, m_fast, m_slow, trig, sl, tp, rsi_p=14):
    ix = _mtf_frame(pair, h1_fast, h1_slow, m_fast, m_slow, rsi_p); n = len(ix['c'])
    split = int(n*0.6)
    a = dict(pair=pair, h1_fast=h1_fast, h1_slow=h1_slow, m_fast=m_fast,
             m_slow=m_slow, trig=trig, sl=sl, tp=tp, rsi_p=rsi_p)
    ins = backtest_mtf(**a, lo_i=0, hi_i=split)
    out = backtest_mtf(**a, lo_i=split, hi_i=n)
    if not ins or not out: return False, {}
    p,q = int(n/3), int(2*n/3); seg_ok = True
    for lo_i,hi_i in [(0,p),(p,q),(q,n)]:
        r = backtest_mtf(**a, lo_i=lo_i, hi_i=hi_i)
        if not r or r['exp'] <= 0: seg_ok = False; break
    passed = (ins['pf']>=1.25 and ins['exp']>0 and
              out['pf']>=1.3 and out['exp']>0 and out['n']>=80 and seg_ok)
    return passed, dict(in_sample=ins, out_sample=out)
