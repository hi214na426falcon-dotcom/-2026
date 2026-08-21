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

def _cfg(family, pair, base, prm, adx=0, sess='all', atr=0.0, htf=0):
    return dict(family=family, pair=pair, base=base, prm=list(prm),
                adx_thr=adx, sess=sess, atr_mult=atr, htf=htf)

def config_id(cfg):
    prm = ','.join(map(str, cfg['prm']))
    return (f"{cfg['pair']}|{cfg['base']}|{prm}|adx{cfg['adx_thr']}|"
            f"{cfg['sess']}|atr{cfg['atr_mult']}|htf{cfg['htf']}")

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

# ---------------- ファミリー5: 近傍(惜しかった/偶然勝った点の周り) ----------------
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
        for df in (-10,-5,0,5,10):
            for ds in (-40,-20,0,20,40):
                for dsl in (-5,0,5):
                    for dtp in (-20,0,20):
                        f=f0+df; s=s0+ds; sl=sl0+dsl; tp=tp0+dtp
                        if f<2 or s<=f or sl<5 or tp<10: continue
                        cfg=_cfg('neighborhood',pair,base,(f,s,r,sl,tp,bb),
                                 adx=adx0,sess=sess0,atr=atr0,htf=htf0)
                        cid=config_id(cfg)
                        if cid in seen: continue
                        seen.add(cid)
                        yield cfg

# 実行順(neighborhood を最優先=偶然勝った点の裏取りを毎日まず消化)
FAMILIES = [fam_neighborhood, fam_composite, fam_atr, fam_mtf, fam_revert]

def all_configs():
    for fam in FAMILIES:
        for cfg in fam():
            yield cfg
