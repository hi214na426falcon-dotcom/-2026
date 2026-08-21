"""
日次自走ドライバ(毎朝の報告用)
=====================================
毎日: 未検証 config を「できるだけ多く」消化し、累計を更新、生存者は自動で裏取り、
      朝の報告(results/report_<date>.md)を書き、要約を stdout に出す。

方針(ひなさんの指示):
  - 生き残ったやつがあれば詳しく、無ければ「昨日 N通り不発 / 累計 M通り」だけ。
  - 同じ手法でも数値をいじる(space.py の広めグリッド)。
  - 偶然勝った/惜しい点は seed に積み、翌日その周辺を密に攻める(fam_neighborhood)。
  - 行けそうな型は全部(composite/atr/mtf/revert)。毎日できるだけ多く。

使い方:
  python3 daily.py                 # 今日ぶんを回して報告(既定 budget)
  python3 daily.py --max 40000     # 上限件数を変える
  python3 daily.py --report-only   # 回さず直近の報告だけ表示
"""
import sys, os, json, time, datetime
import core, core2, space

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, '..', 'results')
MASTER = os.path.join(RESULTS, 'master.json')
SEEDS = space.NEARMISS_FILE

MAX_NEW_PER_DAY = 30000     # 1日に新規で回す上限(compute ~15-18分目安)
TIME_BUDGET_S   = 1500      # 時間上限(秒)。どちらか先に達したら止める
FLUSH_EVERY     = 500
COMMIT_EVERY    = 3000
# 近傍seed化のしきい値(惜しい/偶然勝った点)
NEAR_INS_PF = 1.2
NEAR_OUT_PF = 1.15

def _now(): return datetime.datetime.now()

def load_master():
    if os.path.exists(MASTER):
        try:
            m = json.load(open(MASTER)); m['done'] = set(m.get('done_ids', [])); return m
        except Exception: pass
    return dict(done_ids=[], done=set(), survivors=[], scanned_total=0,
                days=[], seeds=[], started=_now().isoformat())

def save_master(m):
    m['done_ids'] = sorted(m['done'])
    tmp = MASTER + '.tmp'
    json.dump({k:v for k,v in m.items() if k!='done'}, open(tmp,'w'),
              ensure_ascii=False, indent=1)
    os.replace(tmp, MASTER)

def save_seeds(m):
    json.dump(dict(seeds=m['seeds']), open(SEEDS,'w'), ensure_ascii=False, indent=1)

def git_save(msg):
    import subprocess
    try:
        root = os.path.abspath(os.path.join(HERE, '..', '..'))
        def g(*a): return subprocess.run(['git','-C',root]+list(a),
                                         capture_output=True, text=True, timeout=150)
        g('add','ea-research/results')
        r = g('commit','-m',msg)
        if 'nothing to commit' in (r.stdout+r.stderr): return
        for w in (0,2,4,8,16):
            if w: time.sleep(w)
            g('pull','--rebase','-X','ours','origin','HEAD')
            if g('push','origin','HEAD').returncode==0: return
    except Exception as e:
        print('  [git skip]', repr(e)[:70], flush=True)

# ---------- 1 config 評価 ----------
def evaluate(cfg):
    p, det = core2.validate_survivor2(cfg['base'], tuple(cfg['prm']), cfg['pair'],
                adx_thr=cfg['adx_thr'], sess=cfg['sess'],
                atr_mult=cfg['atr_mult'], htf=cfg['htf'])
    ins = det.get('in_sample'); out = det.get('out_sample')
    return p, ins, out

def rec(cfg, ins, out, passed):
    r = dict(id=space.config_id(cfg), family=cfg['family'], pair=cfg['pair'],
             base=cfg['base'], params=cfg['prm'], adx_thr=cfg['adx_thr'],
             sess=cfg['sess'], atr_mult=cfg['atr_mult'], htf=cfg['htf'],
             in_pf=round(ins['pf'],3), out_pf=round(out['pf'],3),
             out_exp=round(out['exp'],3), out_n=out['n'],
             out_wr=round(out['wr'],2), out_maxdd=round(out['maxdd'],1),
             passed=bool(passed))
    return r

# ---------- 生存者の自動裏取り(近傍ロバスト性 + 実スプレッド) ----------
def stress_test(cfg):
    base=cfg['base']; pair=cfg['pair']; f,s,r,sl,tp,bb=cfg['prm']
    kw=dict(adx_thr=cfg['adx_thr'], sess=cfg['sess'], atr_mult=cfg['atr_mult'], htf=cfg['htf'])
    def ok(prm):
        p,det=core2.validate_survivor2(base,tuple(prm),pair,**kw)
        return bool(p)
    neigh=[]
    for df in (-10,-5,5,10):
        if f+df>=2 and f+df<s: neigh.append((f+df,s,r,sl,tp,bb))
    for ds in (-40,-20,20,40):
        if s+ds>f: neigh.append((f,s+ds,r,sl,tp,bb))
    for dt in (-20,20):
        if tp+dt>=10: neigh.append((f,s,r,sl,tp+dt,bb))
    npass=sum(ok(p) for p in neigh); nfrac = npass/max(1,len(neigh))
    # スプレッド感度(保守値 ×1.3, ×1.6 に上げても通るか)
    base_sp=core.SPR_MAP[pair]; spread_ok=True
    try:
        for k in (1.3,1.6):
            core.SPR_MAP[pair]=base_sp*k
            p,det=core2.validate_survivor2(base,tuple(cfg['prm']),pair,**kw)
            if not p: spread_ok=False; break
    finally:
        core.SPR_MAP[pair]=base_sp
    verdict = 'ROBUST' if (nfrac>=0.5 and spread_ok) else 'FLUKE'
    return dict(neighbor_pass=npass, neighbor_total=len(neigh),
                neighbor_frac=round(nfrac,2), spread_robust=spread_ok, verdict=verdict)

# ---------- 報告書き出し ----------
def write_report(m, today, scanned_today, new_survivors, verdicts):
    date=today.strftime('%Y-%m-%d')
    robust=[s for s in new_survivors if verdicts.get(s['id'],{}).get('verdict')=='ROBUST']
    lines=[f"# EA探索 朝の報告 {date}", ""]
    if robust:
        lines.append(f"## ★ 裏取りを通った候補 {len(robust)}件(要チェック)")
        for s in robust:
            v=verdicts[s['id']]
            lines += [
             f"- **{s['pair']} / {s['base']} / {s['family']}** params={s['params']} "
             f"adx{s['adx_thr']} {s['sess']} atr{s['atr_mult']} htf{s['htf']}",
             f"  - out_pf={s['out_pf']} 勝率{s['out_wr']}% n={s['out_n']} exp={s['out_exp']}pips maxDD={s['out_maxdd']}pips",
             f"  - 近傍ロバスト {v['neighbor_pass']}/{v['neighbor_total']}通過 / 実スプレッド{'耐えた' if v['spread_robust'] else '脱落'} → **{v['verdict']}**",
             f"  - 次: 別期間データ・デモ3ヶ月フォワード(README「生存者が出たら」)",
            ]
    other=[s for s in new_survivors if s not in robust]
    if other:
        lines += ["", f"## 素通り生存 {len(other)}件(ただし裏取りで FLUKE=まぐれ判定)"]
        for s in other:
            v=verdicts.get(s['id'],{})
            lines.append(f"- {s['pair']}/{s['base']} params={s['params']} out_pf={s['out_pf']} "
                         f"→ 近傍{v.get('neighbor_pass','?')}/{v.get('neighbor_total','?')} "
                         f"スプレッド{'耐' if v.get('spread_robust') else '脱'} = FLUKE")
    if not new_survivors:
        lines.append("## 生存ゼロ")
    lines += ["",
      f"## 数字",
      f"- 昨日(今回)試した数: **{scanned_today} 通り**",
      f"- 累計: **{m['scanned_total']} 通り**",
      f"- 累計 素通り生存: {len(m['survivors'])}件 / うち裏取り通過(ROBUST): "
      f"{sum(1 for x in m['survivors'] if x.get('verdict')=='ROBUST')}件",
      f"- 近傍seed(翌日周辺を攻める惜しい点): {len(m['seeds'])}件",
    ]
    path=os.path.join(RESULTS, f"report_{today.strftime('%Y%m%d')}.md")
    open(path,'w').write("\n".join(lines))
    open(os.path.join(RESULTS,'report_latest.md'),'w').write("\n".join(lines))
    return "\n".join(lines)

def main():
    args=sys.argv[1:]
    if '--report-only' in args:
        p=os.path.join(RESULTS,'report_latest.md')
        print(open(p).read() if os.path.exists(p) else "報告はまだありません")
        return
    max_new = MAX_NEW_PER_DAY
    if '--max' in args: max_new=int(args[args.index('--max')+1])

    m=load_master()
    today=_now(); t0=time.time()
    scanned_today=0; new_survivors=[]; verdicts={}; new_seeds=0
    since_flush=0; since_commit=0
    print(f"[daily {today:%Y-%m-%d %H:%M}] 累計 {m['scanned_total']} / 上限 {max_new} / 時間 {TIME_BUDGET_S}s", flush=True)

    for cfg in space.all_configs():
        if scanned_today>=max_new or (time.time()-t0)>=TIME_BUDGET_S: break
        cid=space.config_id(cfg)
        if cid in m['done']: continue
        passed, ins, out = evaluate(cfg)
        m['done'].add(cid); m['scanned_total']+=1; scanned_today+=1
        since_flush+=1; since_commit+=1
        if ins and out:
            if passed:
                r=rec(cfg,ins,out,True)
                v=stress_test(cfg); r['verdict']=v['verdict']
                m['survivors'].append(r); new_survivors.append(r); verdicts[r['id']]=v
                print(f"  !!! 生存 {cid} out_pf={r['out_pf']} → 裏取り {v['verdict']}", flush=True)
            # 近傍seed(惜しい/偶然勝った点)
            if ins['pf']>=NEAR_INS_PF and out['pf']>=NEAR_OUT_PF:
                seed=dict(pair=cfg['pair'],base=cfg['base'],prm=cfg['prm'],
                          adx_thr=cfg['adx_thr'],sess=cfg['sess'],
                          atr_mult=cfg['atr_mult'],htf=cfg['htf'])
                if seed not in m['seeds']:
                    m['seeds'].append(seed); new_seeds+=1
        if since_flush>=FLUSH_EVERY:
            since_flush=0; save_master(m); save_seeds(m)
            rate=scanned_today/max(1e-9,time.time()-t0)
            print(f"  進捗 今日{scanned_today}/{max_new} 累計{m['scanned_total']} "
                  f"{rate:.0f}cfg/s 生存{len(new_survivors)} seed+{new_seeds}", flush=True)
        if since_commit>=COMMIT_EVERY:
            since_commit=0; save_master(m); save_seeds(m)
            git_save(f"chore(ea): daily checkpoint total={m['scanned_total']}")

    # 当日締め
    m['days'].append(dict(date=today.strftime('%Y-%m-%d'), scanned=scanned_today,
                          survivors=len(new_survivors), cumulative=m['scanned_total']))
    save_master(m); save_seeds(m)
    report=write_report(m, today, scanned_today, new_survivors, verdicts)
    git_save(f"report(ea): {today:%Y-%m-%d} scanned={scanned_today} total={m['scanned_total']} survivors={len(new_survivors)}")
    print("\n===== REPORT =====\n"+report, flush=True)

if __name__=='__main__':
    main()
