"""
拡張検証エンジン (core.py の上に "次の階層" を足す)
=====================================================
core.py の鉄の掟をそのまま継承する。外さない:
  1. 1エントリー=1ポジション。マーチン/ナンピン禁止。
  2. 損切りは固定(ATR動的の場合もエントリー時に確定し、動かさない)。
  3. スプレッド(コスト)を必ず引く。
  4. 判定は out-of-sample。前半6割で作り、後半4割で答え合わせ。
  5. 3分割で全区間プラスを要求(まぐれ排除)。

【この階層で足すもの】
  - session フィルタ: 取引する時間帯を絞る(ロンドン/NY/オーバーラップ)。
  - ADX フィルタ: トレンド強度がしきい値以上のときだけ入る。
  - ATR 動的ストップ: 損切り/利確を固定pipsでなくATR倍で置く(建値で確定)。
  ※ MTF(複数時間足)は未実装。m15データ取得可(確認済)なので次の階層。

【カーブフィッティング警告(core.py と同じ)】
  フィルタや自由度を足すほど「まぐれ生存者」は必ず増える。
  生存者が出ても喜ぶな。validate_survivor() を必ず通し、その先の
  別データ・実スプレッド・デモフォワードで裏を取れ。
"""
import pandas as pd, numpy as np, os
import core  # load / PIP_MAP / SPR_MAP / DATA_DIR / signal を再利用

# ---- データ読み込み(時刻付き)。時間帯フィルタに hour が要る ----
_CACHE = {}
def load_full(pair):
    """OHLC と各足の hour(broker時刻)をキャッシュ付きで返す。"""
    if pair in _CACHE:
        return _CACHE[pair]
    df = pd.read_csv(os.path.join(core.DATA_DIR, f'{pair}.csv'))
    o = (df['open']/100000).values
    h = (df['high']/100000).values
    l = (df['low']/100000).values
    c = (df['close']/100000).values
    hour = pd.to_datetime(df['Date']).dt.hour.values
    _CACHE[pair] = (o, h, l, c, hour)
    return _CACHE[pair]

# ---- 指標(core.indicators に ADX を足したもの)----
_IX_CACHE = {}
def indicators2(pair, fast, slow, rsi_p=14, bb_p=20, adx_p=14):
    key = (pair, fast, slow, rsi_p, bb_p, adx_p)
    if key in _IX_CACHE:
        return _IX_CACHE[key]
    o, h, l, c, hour = load_full(pair)
    ix = core.indicators(c, h, l, fast, slow, rsi_p, bb_p)
    ix['adx'] = _adx(h, l, c, adx_p)
    ix['hour'] = hour
    _IX_CACHE[key] = ix
    return ix

def _adx(h, l, c, p=14):
    h = pd.Series(h); l = pd.Series(l); c = pd.Series(c)
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/p, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/p, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/p, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/p, adjust=False).mean().values

# ---- 時間帯ウィンドウ(broker時刻 hour ベース)----
# データは1ソースの broker 時刻。絶対の正しさより「時間帯を絞るとエッジが出るか」の検証。
SESSIONS = {
    'all':      None,
    'london':   (7, 16),    # ロンドン
    'ny':       (13, 22),   # ニューヨーク
    'overlap':  (13, 16),   # ロンドン×NY オーバーラップ(一番厚い)
    'asia':     (0, 8),     # アジア
}
def _in_session(hour_i, sess):
    w = SESSIONS[sess]
    if w is None: return True
    s, e = w
    return s <= hour_i < e

# ---- 検証本体。core.backtest と同じ鉄の掟。フィルタ(adx/session)と ----
# ---- ATR動的ストップを追加。base はロジック名(core.LOGICS)。 ----
_HTF_CACHE = {}
def _htf_sma(pair, htf):
    """MTF-lite: 上位足レジーム代理として close の長期SMA。
    真の複数時間足(m15取得)ではなく、同一H1系列での上位足方向フィルタ。"""
    key = (pair, htf)
    if key in _HTF_CACHE: return _HTF_CACHE[key]
    o, h, l, c, hour = load_full(pair)
    sma = pd.Series(c).rolling(htf).mean().values
    _HTF_CACHE[key] = sma
    return sma

def backtest2(base, prm, pair, adx_thr=0, sess='all', atr_mult=0.0, htf=0,
              max_bars=0, be_trig=0.0, trail=False,
              lo_i=None, hi_i=None):
    """
    prm=(fast,slow,rsi_p,sl,tp,bb_p)。
    adx_thr>0 なら ADX がその値以上のときだけエントリー。
    sess で時間帯を制限。
    atr_mult>0 なら sl/tp を無視し ATR*mult / ATR*mult*(tp/sl) で建値確定。
    htf>0 なら上位足レジーム(長期SMA)方向に一致するエントリーだけ許可(MTF-lite)。
    --- 出口ロジック(鉄の掟: 初期損切りは必ず入る。以下は"有利方向にだけ"動かす)---
    max_bars>0 : そのバー数を超えたら成行手仕舞い(時間切れ)。
    be_trig>0  : 含み益が初期リスク*be_trig に達したら損切りを建値へ(建値移動)。
    trail=True : 含み益が乗ったら、初期リスク幅を保って損切りを追従(トレーリング)。
    """
    fast, slow, rsi_p, sl, tp, bb_p = prm
    o, h, l, c, hour = load_full(pair)
    ix = indicators2(pair, fast, slow, rsi_p, bb_p)
    adx = ix['adx']; atr = ix['atr']
    hsma = _htf_sma(pair, htf) if htf > 0 else None
    pip = core.PIP_MAP.get(pair, 0.0001); sp = core.SPR_MAP[pair]*pip
    n = len(c)
    _floor = max(slow+2, bb_p+2, 16, (htf+2 if htf else 0))
    lo_i = _floor if lo_i is None else max(lo_i, _floor)
    hi_i = n if hi_i is None else hi_i
    tp_ratio = tp/sl if sl else 2.0
    dyn = (max_bars > 0 or be_trig > 0 or trail)
    trades = []; pos = None
    for i in range(lo_i, hi_i):
        if pos:
            d, e, s, t, ei, risk, fav = pos
            if d == 1:
                if l[i] <= s: trades.append((s-e)-sp); pos=None
                elif h[i] >= t: trades.append((t-e)-sp); pos=None
            else:
                if h[i] >= s: trades.append((e-s)-sp); pos=None
                elif l[i] <= t: trades.append((e-t)-sp); pos=None
            if pos and dyn:
                d, e, s, t, ei, risk, fav = pos
                # 有利方向の到達点を更新
                fav = max(fav, h[i]) if d == 1 else min(fav, l[i])
                # 時間切れ(成行手仕舞い)
                if max_bars > 0 and (i - ei) >= max_bars:
                    px = c[i]
                    trades.append(((px-e) if d == 1 else (e-px)) - sp); pos = None
                else:
                    ns = s
                    if d == 1:
                        prof = fav - e
                        if be_trig > 0 and prof >= be_trig*risk: ns = max(ns, e)
                        if trail and prof > risk: ns = max(ns, fav - risk)
                    else:
                        prof = e - fav
                        if be_trig > 0 and prof >= be_trig*risk: ns = min(ns, e)
                        if trail and prof > risk: ns = min(ns, fav + risk)
                    pos = (d, e, ns, t, ei, risk, fav)
        if pos: continue
        # --- フィルタ ---
        if adx_thr > 0 and not (adx[i] >= adx_thr): continue
        if not _in_session(hour[i], sess): continue
        sig = core.signal(base, ix, i, c)
        if sig == 0: continue
        if hsma is not None:  # 上位足レジーム方向に一致しないエントリーは捨てる
            if sig == 1 and not (c[i] > hsma[i]): continue
            if sig == -1 and not (c[i] < hsma[i]): continue
        e = c[i]
        if atr_mult > 0 and atr[i] > 0:
            risk = atr_mult*atr[i]; rew = risk*tp_ratio
        else:
            risk = sl*pip; rew = tp*pip
        if sig == 1: pos = (1, e, e-risk, e+rew, i, risk, e)
        else:        pos = (-1, e, e+risk, e-rew, i, risk, e)
    tr = np.array(trades)
    if len(tr) < 40: return None
    w = tr[tr>0]; lsr = tr[tr<=0]
    pf = w.sum()/abs(lsr.sum()) if lsr.sum()!=0 else 99
    eq = np.cumsum(tr); peak=np.maximum.accumulate(eq); maxdd=(peak-eq).max()
    return dict(n=len(tr), wr=len(w)/len(tr)*100, pf=pf,
                exp=tr.mean()/pip, maxdd=maxdd/pip, total=eq[-1]/pip)

def validate_survivor2(base, prm, pair, adx_thr=0, sess='all', atr_mult=0.0, htf=0,
                       max_bars=0, be_trig=0.0, trail=False):
    """core.validate_survivor と同じ関門。フィルタ付きで判定。"""
    o, h, l, c, hour = load_full(pair); n=len(c); split=int(n*0.6)
    kw = dict(adx_thr=adx_thr, sess=sess, atr_mult=atr_mult, htf=htf,
              max_bars=max_bars, be_trig=be_trig, trail=trail)
    ins = backtest2(base, prm, pair, lo_i=0, hi_i=split, **kw)
    out = backtest2(base, prm, pair, lo_i=split, hi_i=n, **kw)
    if not ins or not out: return False, {}
    a, b = int(n/3), int(2*n/3)
    seg_ok = True
    for lo_i, hi_i in [(0, a), (a, b), (b, n)]:
        r = backtest2(base, prm, pair, lo_i=lo_i, hi_i=hi_i, **kw)
        if not r or r['exp'] <= 0: seg_ok = False; break
    passed = (ins['pf']>=1.25 and ins['exp']>0 and
              out['pf']>=1.3 and out['exp']>0 and out['n']>=80 and seg_ok)
    return passed, dict(in_sample=ins, out_sample=out)

# 複合フィルタ探索で base に使う型(トレンド追随/押し目系。ADX順張りと相性)
COMPOSITE_BASES = ['trend', 'breakout', 'pullback', 'trend_rsi']
