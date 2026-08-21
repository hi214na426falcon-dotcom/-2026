"""
再開可能な探索ランナー (チェックポイント + git保存)
=====================================================
狙い: トークン制限やコンテナ再生成で途中で止まっても、
      state ファイルから "続きから" 再開できるようにする。

使い方:
    python3 runner.py composite        # 複合フィルタ(ADX+時間帯) ← 本命
    python3 runner.py atr              # ATR動的ストップ
    python3 runner.py baseline         # 単純指標(再現用。全滅済み)
    python3 runner.py composite --no-git   # git自動保存を切る

仕組み:
  - 各 config を評価するたび results/state_<run>.json を更新(done_ids に追記)。
  - 再起動時は state を読み、done_ids にある config は飛ばす → 続きから。
  - COMMIT_EVERY 件ごとに git add/commit/push(失敗しても計算は止めない)。
  - 生存者は survivors に貯め、state と別に survivors_<run>.json にも出す。

★カーブフィッティング警告: 生存者が出ても喜ぶな。README/core.py の裏取り手順を必ず通せ。
"""
import sys, os, json, time, itertools, subprocess, hashlib, datetime
import core, core2

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, '..', 'results')
COMMIT_EVERY = 200           # 何件ごとに git 保存するか
FLUSH_EVERY = 25             # 何件ごとに state をディスクに書くか
PAIRS = ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF',
         'USDCAD','EURJPY','GBPJPY','EURGBP','XAUUSD']

# ============ 探索空間の定義。run名 -> config のジェネレータ ============
def gen_composite():
    """複合フィルタ: base型 × params × ADXしきい値 × 時間帯 × pair。"""
    fasts=[10,20,50]; slows=[100,200]; sls=[20,40]; tps=[40,80]
    adxs=[0,20,25]; sessions=['all','london','ny','overlap']
    for pair in PAIRS:
        for base in core2.COMPOSITE_BASES:
            for fast,slow,sl,tp in itertools.product(fasts,slows,sls,tps):
                if fast>=slow: continue
                prm=(fast,slow,14,sl,tp,20)
                for adx in adxs:
                    for sess in sessions:
                        yield dict(run='composite', pair=pair, base=base,
                                   prm=list(prm), adx_thr=adx, sess=sess, atr_mult=0.0)

def gen_atr():
    """ATR動的ストップ: base型 × params × ATR倍 × pair(フィルタは素)。"""
    fasts=[10,20,50]; slows=[100,200]; atrs=[1.5,2.0,3.0]; tps=[40,80]
    for pair in PAIRS:
        for base in core2.COMPOSITE_BASES:
            for fast,slow,tp in itertools.product(fasts,slows,tps):
                if fast>=slow: continue
                # ATRモードでは sl は tp比の分母として使う(atr_mult>0で建値確定)
                prm=(fast,slow,14,20,tp,20)
                for am in atrs:
                    yield dict(run='atr', pair=pair, base=base,
                               prm=list(prm), adx_thr=0, sess='all', atr_mult=am)

def gen_baseline():
    """単純指標の再現(全滅確認用)。"""
    fasts=[10,20,30]; slows=[50,100,200]; sls=[20,40]; tps=[40,80,120]
    for pair in PAIRS:
        for base in core.LOGICS:
            for fast,slow,sl,tp in itertools.product(fasts,slows,sls,tps):
                if fast>=slow: continue
                yield dict(run='baseline', pair=pair, base=base,
                           prm=[fast,slow,14,sl,tp,20], adx_thr=0, sess='all', atr_mult=0.0)

GENERATORS = {'composite': gen_composite, 'atr': gen_atr, 'baseline': gen_baseline}

def config_id(cfg):
    prm = ','.join(map(str, cfg['prm']))
    return f"{cfg['pair']}|{cfg['base']}|{prm}|adx{cfg['adx_thr']}|{cfg['sess']}|atr{cfg['atr_mult']}"

# ============ state 入出力 ============
def state_path(run): return os.path.join(RESULTS, f'state_{run}.json')
def surv_path(run):  return os.path.join(RESULTS, f'survivors_{run}.json')

def load_state(run):
    p = state_path(run)
    if os.path.exists(p):
        try:
            s = json.load(open(p))
            s['done'] = set(s.get('done_ids', []))
            return s
        except Exception:
            pass
    return dict(run=run, done_ids=[], done=set(), survivors=[],
                scanned=0, started=datetime.datetime.now().isoformat(), updated=None)

def save_state(state):
    state['done_ids'] = sorted(state['done'])
    state['updated'] = datetime.datetime.now().isoformat()
    os.makedirs(RESULTS, exist_ok=True)
    tmp = state_path(state['run']) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({k:v for k,v in state.items() if k!='done'}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, state_path(state['run']))
    with open(surv_path(state['run']), 'w') as f:
        json.dump(dict(run=state['run'], scanned=state['scanned'],
                       n_survivors=len(state['survivors']),
                       survivors=state['survivors']), f, ensure_ascii=False, indent=2)

def git_save(run, msg):
    """state を git に保存。失敗しても計算は止めない(ベストエフォート)。"""
    try:
        env = dict(os.environ)
        root = os.path.abspath(os.path.join(HERE, '..', '..'))
        def g(*a):
            return subprocess.run(['git','-C',root]+list(a), capture_output=True, text=True, timeout=120)
        g('add', 'ea-research/results')
        r = g('commit', '-m', msg)
        if 'nothing to commit' in (r.stdout + r.stderr):
            return
        for wait in (0, 2, 4, 8):
            if wait: time.sleep(wait)
            g('pull', '--rebase', '-X', 'ours', 'origin', 'HEAD')  # state衝突は自分優先
            p = g('push', 'origin', 'HEAD')
            if p.returncode == 0:
                return
    except Exception as e:
        print('  [git save skipped]', repr(e)[:80], flush=True)

# ============ 1 config を評価 ============
def evaluate(cfg):
    passed, det = core2.validate_survivor2(
        cfg['base'], tuple(cfg['prm']), cfg['pair'],
        adx_thr=cfg['adx_thr'], sess=cfg['sess'], atr_mult=cfg['atr_mult'])
    if not passed: return None
    out = det['out_sample']; ins = det['in_sample']
    return dict(id=config_id(cfg), pair=cfg['pair'], base=cfg['base'],
                params=cfg['prm'], adx_thr=cfg['adx_thr'], sess=cfg['sess'],
                atr_mult=cfg['atr_mult'],
                in_pf=round(ins['pf'],3), out_pf=round(out['pf'],3),
                out_exp=round(out['exp'],3), out_n=out['n'],
                out_wr=round(out['wr'],2), out_maxdd=round(out['maxdd'],1))

def main():
    run = sys.argv[1] if len(sys.argv) > 1 else 'composite'
    use_git = '--no-git' not in sys.argv
    if run not in GENERATORS:
        print('run は', list(GENERATORS), 'から選ぶ'); sys.exit(1)

    configs = list(GENERATORS[run]())
    total = len(configs)
    state = load_state(run)
    print(f"[{run}] 全 {total} config / 既完了 {len(state['done'])} / 生存 {len(state['survivors'])}", flush=True)

    t0 = time.time(); since_commit = 0; new_since_flush = 0
    for idx, cfg in enumerate(configs):
        cid = config_id(cfg)
        if cid in state['done']:
            continue
        surv = evaluate(cfg)
        state['done'].add(cid)
        state['scanned'] += 1
        new_since_flush += 1; since_commit += 1
        if surv:
            state['survivors'].append(surv)
            print(f"  !!! 生存候補 {cid}  out_pf={surv['out_pf']} out_n={surv['out_n']}", flush=True)
        if new_since_flush >= FLUSH_EVERY:
            save_state(state); new_since_flush = 0
            done = len(state['done']); rate = state['scanned']/max(1e-9, time.time()-t0)
            eta = (total-done)/max(1e-9, rate)
            print(f"  進捗 {done}/{total} ({100*done/total:.1f}%) "
                  f"{rate:.1f}cfg/s ETA {eta/60:.1f}min 生存{len(state['survivors'])}", flush=True)
        if use_git and since_commit >= COMMIT_EVERY:
            save_state(state)
            git_save(run, f"chore(ea): checkpoint {run} {len(state['done'])}/{total}")
            since_commit = 0

    save_state(state)
    if use_git:
        git_save(run, f"chore(ea): finish {run} scanned={state['scanned']} survivors={len(state['survivors'])}")
    print(f"\n[{run}] 完了。スキャン {state['scanned']} / 生存 {len(state['survivors'])} 件", flush=True)
    if state['survivors']:
        print("生存者あり。喜ぶ前に README の裏取り手順(別データ/実スプレッド/デモ)を必ず通せ。", flush=True)
    else:
        print("生存ゼロ。この階層にもエッジ無し。次へ。", flush=True)

if __name__ == '__main__':
    main()
