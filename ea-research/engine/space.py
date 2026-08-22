"""
探索空間の定義(手法ファミリー群)
=====================================
「行けると思ったんは全部試す」を、複数ファミリーの config ジェネレータで表す。
daily.py がこれを回し、未検証(done外)を毎日できるだけ消化する。

各 config は dict:
  family, pair, base, prm=[fast,slow,rsi,sl,tp,bb], adx_thr, sess, atr_mult, htf
config_id は手法の同一性(family抜き)で作り、ファミリー間の重複を自動で除く。

★カーブフィッティング警告: 空間を広げるほど「まぐれ生存者」は必ず増える。
  生存判定のあと、近傍ロバスト性+実スプレッドで必ず裏を取る(daily.py が自動で当てる)。
"""
import itertools, os, json
import core, core2

PAIRS = ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF',
         'USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']
TREND_BASES = ['trend','breakout','pullback','trend_rsi']
REVERT_BASES = ['revert_rsi','revert_bb']
HERE = os.path.dirname(__file__)
NEARMISS_FILE = os.path.join(HERE, '..', 'results', 'nearmiss_seeds.json')

def _cfg(family, pair, base, prm, adx=0, sess='all', atr=0.0, htf=0,
         max_bars=0, be_trig=0.0, trail=False):
    return dict(family=family, pair=pair, base=base, prm=list(prm),
                adx_thr=adx, sess=sess, atr_mult=atr, htf=htf,
                max_bars=max_bars, be_trig=be_trig, trail=trail)

def _cfg_mtf(pair, h1_fast, h1_slow, m_fast, m_slow, trig, sl, tp, rsi_p=14):
    return dict(kind='mtf', family='mtf_true', pair=pair, h1_fast=h1_fast,
                h1_slow=h1_slow, m_fast=m_fast, m_slow=m_slow, trig=trig,
                sl=sl, tp=tp, rsi_p=rsi_p)

def config_id(cfg):
    if cfg.get('kind') == 'mtf':
        return (f"MTF|{cfg['pair']}|h{cfg['h1_fast']}/{cfg['h1_slow']}|"
                f"m{cfg['m_fast']}/{cfg['m_slow']}|{cfg['trig']}|"
                f"sl{cfg['sl']}|tp{cfg['tp']}|r{cfg['rsi_p']}")
    prm = ','.join(map(str, cfg['prm']))
    cid = (f"{cfg['pair']}|{cfg['base']}|{prm}|adx{cfg['adx_thr']}|"
           f"{cfg['sess']}|atr{cfg['atr_mult']}|htf{cfg['htf']}")
    # 出口ロジックは非デフォルト時だけ付与(既存idを壊さない=再計算を防ぐ)
    mb=cfg.get('max_bars',0); be=cfg.get('be_trig',0.0); tr=cfg.get('trail',False)
    if mb or be or tr:
        cid += f"|mb{mb}|be{be}|tr{int(bool(tr))}"
    return cid

# ---------------- ファミリー1: 複合フィルタ(広めグリッド) ----------------
def fam_composite():
    fasts=[5,10,20,30,50]; slows=[100,150,200,300]
    sls=[20,30,40]; tps=[40,60,80,120]
    adxs=[0,20,25,30]; sessions=['all','london','ny','overlap']
    for pair in PAIRS:
        for base in TREND_BASES:
            for f,s in itertools.product(fasts,slows):
                if f>=s: continue
                for sl,tp in itertools.product(sls,tps):
                    for adx in adxs:
                        for sess in sessions:
                            yield _cfg('composite',pair,base,(f,s,14,sl,tp,20),adx=adx,sess=sess)

# ---------------- ファミリー2: ATR動的ストップ(広め) ----------------
def fam_atr():
    fasts=[10,20,30,50]; slows=[100,150,200]
    atrs=[1.0,1.5,2.0,2.5,3.0]; tps=[40,60,80,100]; adxs=[0,25]
    for pair in PAIRS:
        for base in TREND_BASES:
            for f,s in itertools.product(fasts,slows):
                if f>=s: continue
                for am in atrs:
                    for tp in tps:
                        for adx in adxs:
                            yield _cfg('atr',pair,base,(f,s,14,20,tp,20),adx=adx,atr=am)

# ---------------- ファミリー3: MTF-lite(上位足レジーム) ----------------
def fam_mtf():
    fasts=[10,20,30]; slows=[50,100,200]; htfs=[240,480,720]
    sls=[20,40]; tps=[40,80]; adxs=[0,25]
    for pair in PAIRS:
        for base in TREND_BASES:
            for f,s in itertools.product(fasts,slows):
                if f>=s: continue
                for htf in htfs:
                    for sl,tp in itertools.product(sls,tps):
                        for adx in adxs:
                            yield _cfg('mtf',pair,base,(f,s,14,sl,tp,20),adx=adx,htf=htf)

# ---------------- ファミリー4: 逆張り(時間帯フィルタ) ----------------
def fam_revert():
    fasts=[10,20]; slows=[50,100]; sls=[15,20,30]; tps=[20,30,40]
    sessions=['all','london','ny','overlap','asia']
    for pair in PAIRS:
        for base in REVERT_BASES:
            for f,s in itertools.product(fasts,slows):
                if f>=s: continue
                for sl,tp in itertools.product(sls,tps):
                    for sess in sessions:
                        yield _cfg('revert',pair,base,(f,s,14,sl,tp,20),sess=sess)

# ---------------- ファミリー5: 出口ロジック(トレーリング/建値/時間切れ) ----------------
# 固定SL/TPだけでは全滅。出口を賢くするとエッジが出るか?を検証。
def fam_exits():
    fasts=[10,20,30]; slows=[100,200]; sls=[20,40]
    # 出口プリセット: (max_bars, be_trig, trail)
    exits=[
        (0, 1.0, False),   # 建値移動(含み益=1R で損切りを建値へ)
        (0, 0.0, True),    # トレーリング(1R幅で追従)
        (24, 0.0, False),  # 時間切れ 24本(H1で約1日)
        (72, 0.0, False),  # 時間切れ 72本(約3日)
        (48, 1.0, True),   # 時間切れ+トレーリング 合わせ技
    ]
    for pair in PAIRS:
        for base in TREND_BASES:
            for f,s in itertools.product(fasts,slows):
                if f>=s: continue
                for sl in sls:
                    tp = sl*4   # 出口が動くのでTPは遠めに固定(トレーリング主役)
                    for mb,be,tr in exits:
                        yield _cfg('exits',pair,base,(f,s,14,sl,tp,20),
                                   max_bars=mb,be_trig=be,trail=tr)

# ---------------- ファミリー6: 逆張りの内部数値(RSI期間/BB期間を振る) ----------------
# これまで rsi_p=14, bb_p=20 に固定してた軸を初めて動かす。
def fam_internal():
    rsis=[7,14,21]; bbs=[14,20,30]; sls=[15,20,30]; tps=[20,30,40]
    for pair in PAIRS:
        for base in REVERT_BASES:
            for rp in rsis:
                for bb in bbs:
                    for sl,tp in itertools.product(sls,tps):
                        yield _cfg('internal',pair,base,(20,100,rp,sl,tp,bb))

# ---------------- ファミリー8: 真MTF(H1トレンド × M15エントリー) ← 本命 ----------------
def fam_mtf_true():
    h1s=[(20,50),(20,100),(50,200)]      # H1レジーム(fast,slow)
    m15s=[(10,30),(20,50)]               # M15トレンド(fast,slow)
    trigs=['cross','pull','break']       # M15エントリートリガ
    sls=[15,20,30]; tps=[30,40,60,80]
    for pair in PAIRS:
        for hf,hs in h1s:
            for mf,ms in m15s:
                for trig in trigs:
                    for sl in sls:
                        for tp in tps:
                            yield _cfg_mtf(pair,hf,hs,mf,ms,trig,sl,tp)

# ---------------- ファミリー9: 近傍(惜しかった/偶然勝った点の周り) ----------------
# 「運も実力のうち」— out で光った点の数値を細かくずらして、本物か偶然か炙り出す。
def fam_neighborhood():
    if not os.path.exists(NEARMISS_FILE):
        return
    try:
        seeds = json.load(open(NEARMISS_FILE)).get('seeds', [])
    except Exception:
        return
    seen = set()
    for sd in seeds:
        pair=sd['pair']; base=sd['base']; f0,s0,r,sl0,tp0,bb=sd['prm']
        adx0=sd.get('adx_thr',0); sess0=sd.get('sess','all')
        atr0=sd.get('atr_mult',0.0); htf0=sd.get('htf',0)
        mb0=sd.get('max_bars',0); be0=sd.get('be_trig',0.0); tr0=sd.get('trail',False)
        for df in (-10,-5,0,5,10):
            for ds in (-40,-20,0,20,40):
                for dsl in (-5,0,5):
                    for dtp in (-20,0,20):
                        f=f0+df; s=s0+ds; sl=sl0+dsl; tp=tp0+dtp
                        if f<2 or s<=f or sl<5 or tp<10: continue
                        cfg=_cfg('neighborhood',pair,base,(f,s,r,sl,tp,bb),
                                 adx=adx0,sess=sess0,atr=atr0,htf=htf0,
                                 max_bars=mb0,be_trig=be0,trail=tr0)
                        cid=config_id(cfg)
                        if cid in seen: continue
                        seen.add(cid)
                        yield cfg

# 実行順(neighborhood を最優先=偶然勝った点の裏取りを毎日まず消化)
FAMILIES = [fam_neighborhood, fam_mtf_true, fam_exits, fam_internal,
            fam_composite, fam_atr, fam_mtf, fam_revert]

def all_configs():
    for fam in FAMILIES:
        for cfg in fam():
            yield cfg
