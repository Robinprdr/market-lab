"""Transparent bounded search: exploration only, then immutable frozen JSON."""
import json
import random
import time
import numpy as np
import pandas as pd
from .common import CACHE,OUT,UNIVERSE,HERE,protocol,write,sha,cost
from .evaluate import paths,prepare,condition_mask,scan

ANCHORS={
 'momentum':[['return_15m','>=',.002]],
 'breakout_volume':[['new_high','>=',1],['volume_breakout','>=',1.5]],
 'opening_range':[['or15_breakout','>=',1]],
 'vwap_pullback':[['distance_vwap','>=',0],['return_5m','<=',0],['return_open','>=',.003]],
 'vwap_reclaim':[['vwap_reclaim','>=',1],['impulse_30m','>=',.003]],
 'high_of_day':[['new_high','>=',1],['distance_hod','>=',-.001]],
 'relative_strength':[['rank_15m','>=',.8],['return_15m','>=',.002]],
 'daily_continuation':[['daily_distance_sma50','>=',0],['return_15m','>=',.002]]}

# Fixed, economically legible thresholds; no quantiles from validation/final.
THRESHOLDS={
 'return_5m':[0,.001,.002,.004], 'return_15m':[.001,.003,.005,.01], 'return_30m':[.002,.005,.01],
 'return_60m':[.003,.01,.02], 'return_open':[0,.005,.01,.02], 'acceleration':[0,.001],
 'distance_vwap':[0,.001,.003], 'slope_vwap':[0,.001], 'vwap_hold3':[1],
 'relative_volume':[1,1.5,2,3], 'volume_breakout':[1,1.5,2], 'volume_acceleration':[0,.5,1],
 'volume_z20':[0,1,2], 'volume_percentile':[.7,.9], 'distance_ema9':[0,.001], 'distance_ema20':[0,.002],
 'distance_ema50':[0,.003], 'align_ema9_20':[0,.001], 'align_ema20_50':[0,.001], 'ema_slope':[0,.001],
 'clv':[.6,.8], 'body_range':[.25,.5], 'green_streak':[2,3], 'range_expansion':[1,1.5,2],
 'range_compression':[1,1.5], 'range_position':[.7,.9], 'session_range':[.005,.01,.02],
 'rs_spy_15m':[0,.002,.005], 'rs_spy_30m':[0,.003], 'rs_universe_15m':[0,.002,.005],
 'rank_15m':[.7,.9], 'rank_30m':[.7,.9], 'rank_60m':[.7,.9],
 'daily_return_5':[0,.03], 'daily_return_10':[0,.05], 'daily_return_20':[0,.05,.1],
 'daily_distance_sma20':[0,.03], 'daily_distance_sma50':[0,.05], 'daily_rs_spy_20':[0,.05],
 'daily_spy_distance_sma50':[0], 'or5_distance':[0,.001], 'or15_distance':[0,.001],
 'or30_distance':[0,.001], 'or60_distance':[0,.001]}
WINDOWS={'window_open':(575,660),'window_mid':(660,840),'window_late':(840,950),'window_not_open':(600,950)}

def atoms():
    a=[(k,'>=',v) for k,vs in THRESHOLDS.items() for v in vs]
    a += [(k,'>=',1) for k in WINDOWS]
    a += [('distance_vwap','<=',.003),('distance_vwap','<=',.01),('daily_atr_pct_14','<=',.04)]
    return [list(x) for x in a]

def canonical(conditions):return sorted(conditions,key=lambda x:(x[0],x[1],x[2]))
def key(rule):return json.dumps([rule['family'],canonical(rule['conditions']),rule['horizon_bars']],sort_keys=True)

def generate_initial(cfg):
    # PASS 1: one family anchor plus at most one ancillary feature/time condition.
    rules=[];seen=set()
    for family,anchor in ANCHORS.items():
        additions=[None]+atoms()
        for extra in additions:
            if extra is not None and (extra in anchor or extra[0] in {x[0] for x in anchor}):continue
            conditions=canonical(anchor+([extra] if extra else []))
            if len(conditions)>4:continue
            for horizon in cfg['horizons_bars']:
                r=dict(family=family,conditions=conditions,horizon_bars=horizon,pass_number=1)
                k=key(r)
                if k not in seen:seen.add(k);rules.append(r)
    # Predeclared cap leaves room for combinations; deterministic uniform sampling.
    random.Random(cfg['seed']).shuffle(rules)
    return rules[:min(1600,cfg['maximum_variants'])]

def generate_combinations(initial,summary,cfg):
    # PASS 2 chooses promising features inside each family on exploration data only.
    chosen={};byid={r['id']:r for r in initial}
    for family in ANCHORS:
        sub=summary[(summary.family==family)&summary.trades.ge(300)].sort_values(['positive_years','average_net','pf_net'],ascending=False).head(20)
        values=[]
        for rid in sub.id:
            for a in byid[rid]['conditions']:
                if a not in ANCHORS[family] and a not in values:values.append(a)
        chosen[family]=values or atoms()[:20]
    write(OUT/'exploration_feature_selection.json',chosen)
    rng=random.Random(cfg['seed']+1);seen={key(r) for r in initial};result=[]
    for attempt in range(150000):
        if len(result)+len(initial)>=cfg['maximum_variants']:break
        family=rng.choice(list(ANCHORS));anchor=ANCHORS[family]
        # PASS 3: selected combinations; PASS 4: bounded thresholds from the declared dictionary.
        stage=3 if len(result)<2200 else 4;pool=chosen[family] if stage==3 else atoms()
        extra=rng.sample(pool,min(rng.randint(1,max(1,4-len(anchor))),len(pool)))
        conditions=canonical(anchor+extra)
        if len(conditions)>4 or len({(x[0],x[1]) for x in conditions})<len(conditions):continue
        r=dict(family=family,conditions=conditions,horizon_bars=rng.choice(cfg['horizons_bars']),pass_number=stage);k=key(r)
        if k not in seen:seen.add(k);result.append(r)
    return result

def assign_ids(rules,offset=0):
    for i,r in enumerate(rules):r['id']=f'IV1_{offset+i:05d}'

def evaluate(rules,cfg):
    universe=pd.read_csv(UNIVERSE).ticker.tolist();all_atoms=[]
    for r in rules:
        for a in r['conditions']:
            if a not in all_atoms:all_atoms.append(a)
    conditions=np.full((len(rules),4),-1,np.int32);counts=np.zeros(len(rules),np.int32)
    for i,r in enumerate(rules):
        counts[i]=len(r['conditions'])
        for j,a in enumerate(r['conditions']):conditions[i,j]=all_atoms.index(a)
    horizons=np.array([cfg['horizons_bars'].index(r['horizon_bars']) for r in rules],np.int32)
    total=np.zeros((len(rules),8));annual=np.zeros((6,len(rules),8));contrib=np.zeros((len(rules),len(universe)));tc=np.zeros_like(contrib)
    for month,path in enumerate(paths('exploration')):
        f,eligible,t,ret,exits=prepare(pd.read_parquet(path),cfg)
        for name,(lo,hi) in WINDOWS.items():f[name]=(f.Minute_ET.ge(lo)&f.Minute_ET.lt(hi)).astype(float)
        table=np.ascontiguousarray(np.stack([condition_mask(f,a)&eligible for a in all_atoms]))
        values,c,n=scan(table,conditions,counts,horizons,ret,exits,t,cost(cfg),len(universe));total+=values;annual[int(path.stem[:4])-2018]+=values;contrib+=c;tc+=n
        if (month+1)%12==0:print('search rules',len(rules),'months',month+1,'/ 72',flush=True)
    rows=[]
    for i,r in enumerate(rules):
        n,g,net,sq,wins,pos,neg,stress=total[i];positive=contrib[i].clip(min=0).sum();top=np.argsort(contrib[i])[-5:];removed_n=n-tc[i,top].sum()
        rows.append(dict(id=r['id'],family=r['family'],pass_number=r['pass_number'],conditions=json.dumps(r['conditions']),complexity=len(r['conditions']),horizon_minutes=r['horizon_bars']*5 if r['horizon_bars'] else 'EOD',trades=int(n),average_gross=g/n if n else np.nan,average_net=net/n if n else np.nan,win_rate=wins/n if n else np.nan,pf_net=pos/neg if neg else np.nan,stress_average_net=stress/n if n else np.nan,positive_years=int((annual[:,i,2]>0).sum()),top_ticker_share=contrib[i].max()/positive if positive else 1.,top5_share=contrib[i,top].clip(min=0).sum()/positive if positive else 1.,remove_top5_average_net=(net-contrib[i,top].sum())/removed_n if removed_n else np.nan,**{f'net_{year}':annual[year-2018,i,2]/annual[year-2018,i,0] if annual[year-2018,i,0] else np.nan for year in range(2018,2024)}))
    frame=pd.DataFrame(rows)
    best_year=np.argmax(annual[:,:,2],axis=0)
    denominator=total[:,0]-annual[best_year,np.arange(len(rules)),0]
    numerator=total[:,2]-annual[best_year,np.arange(len(rules)),2]
    frame['remove_best_year_average_net']=np.divide(numerator,denominator,out=np.full(len(rules),np.nan),where=denominator>0)
    for year in range(2018,2024):frame[f'trades_{year}']=annual[year-2018,:,0].astype(int)
    return frame

def verify_frozen():
    path=OUT/'frozen_intraday_candidates.json'
    if sha(path)!=(OUT/'frozen_intraday_candidates.sha256').read_text().strip():raise ValueError('Frozen candidates mutated')
    payload=json.loads(path.read_text())
    if payload['protocol_sha256']!=sha(OUT/'protocol.json'):raise ValueError('Protocol mutated after freeze')
    for name,digest in payload.get('code_sha256',{}).items():
        if sha(HERE/name)!=digest:raise ValueError('Execution/feature code mutated after freeze')
    if payload.get('data_overrides_sha256') and payload['data_overrides_sha256']!=sha(HERE/'data_overrides.json'):raise ValueError('Data overrides mutated after freeze')
    return payload

def main():
    cfg=protocol();target=OUT/'frozen_intraday_candidates.json'
    if target.exists():raise SystemExit('Already frozen; rerunning exploration forbidden')
    start=time.monotonic()
    baselines=[dict(id=f'BASE_{h}',family='baseline',pass_number=0,conditions=[['Minute_ET','>=',570]],horizon_bars=h) for h in cfg['horizons_bars']]
    evaluate(baselines,cfg).to_csv(OUT/'baseline_exploration.csv',index=False)
    initial=generate_initial(cfg);assign_ids(initial);summary=evaluate(initial,cfg)
    more=generate_combinations(initial,summary,cfg);assign_ids(more,len(initial));more_summary=evaluate(more,cfg)
    all_rules=initial+more;all_summary=pd.concat([summary,more_summary],ignore_index=True)
    all_summary.to_csv(OUT/'exploration_summary.csv',index=False);write(OUT/'exploration_rules.json',all_rules)
    eligible=all_summary[(all_summary.trades>=cfg['train_min_trades'])&(all_summary.pf_net>=cfg['train_min_pf'])&(all_summary.average_net>0)&(all_summary.stress_average_net>0)&(all_summary.positive_years>=cfg['train_positive_years'])&(all_summary.top_ticker_share<=cfg['train_top_ticker_share'])&(all_summary.remove_top5_average_net>0)].sort_values(['average_net','pf_net'],ascending=False)
    selected=[];family_count={};seen_horizon=set();lookup={r['id']:r for r in all_rules}
    for row in eligible.itertuples():
        if family_count.get(row.family,0)>=2 or (row.family,row.horizon_minutes) in seen_horizon:continue
        selected.append(lookup[row.id]);family_count[row.family]=family_count.get(row.family,0)+1;seen_horizon.add((row.family,row.horizon_minutes))
        if len(selected)>=cfg['maximum_candidates']:break
    # PASS 5: immutable maximum ten, before any validation dataset is read.
    write(target,dict(protocol_sha256=sha(OUT/'protocol.json'),code_sha256={name:sha(HERE/name) for name in ['common.py','features.py','evaluate.py']},data_overrides_sha256=sha(HERE/'data_overrides.json'),exploration_only=True,candidates=selected,selection='Predeclared net/stress/frequency/stability/concentration gates; max2/family; distinct horizons'))
    (OUT/'frozen_intraday_candidates.sha256').write_text(sha(target)+'\n')
    write(OUT/'search_manifest.json',dict(seconds=time.monotonic()-start,variants=len(all_rules),thresholds=len({tuple(a) for r in all_rules for a in r['conditions']}),dictionary_thresholds=sum(map(len,THRESHOLDS.values())),families=len(ANCHORS),frozen=len(selected),passes={'1':len(initial),'2':'exploration feature selection','3':sum(r['pass_number']==3 for r in more),'4':sum(r['pass_number']==4 for r in more),'5':len(selected)}))
    print('EXPLORATION COMPLETE; frozen',len(selected),flush=True)

if __name__=='__main__':main()
