"""Explicit stages: sample, explore, freeze, validate. No validation in search."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import shutil
import zipfile
import numpy as np
import pandas as pd
from .features import daily_features,intraday_features
from .providers import YahooSampleProvider,CSVProvider,AlpacaProvider,aggregate_minutes,require_complete_sessions
from .search import Lab,explore,rule_mask

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
CACHE=ROOT/'data/cache/research_v2'
OUT=ROOT/'results/research_v2'
DAILY=ROOT/'data/cache/v1_top100/ohlcv.csv'
SAMPLE=ROOT/'data/samples/research_v2_sample.zip'
SAMPLE_FILES=('intraday_1m.csv','intraday_5m.pkl','intraday_daily.csv')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def write_json(path,obj):Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False,default=str)+'\n')
def config():
    cfg=json.loads((HERE/'protocol.json').read_text())
    if sha(ROOT/cfg['universe'])!=cfg['universe_sha256']:raise ValueError('Universe changed')
    return cfg

def freeze_file(path,payload):
    with Path(path).open('x') as f:json.dump(payload,f,indent=2,allow_nan=False,default=str);f.write('\n')
    Path(str(path)+'.sha256').write_text(sha(path)+'\n')

def load_frozen(path):
    if sha(path)!=Path(str(path)+'.sha256').read_text().strip():raise ValueError('Frozen candidates modified')
    obj=json.loads(Path(path).read_text())
    if obj['protocol_sha256']!=sha(HERE/'protocol.json'):raise ValueError('Protocol modified after freeze')
    for name,value in obj['code_sha256'].items():
        if sha(HERE/name)!=value:raise ValueError('Research code modified after freeze: '+name)
    return obj


def prepare(args,cfg):
    p=cfg['intraday']; tickers=p['sample_tickers'] if args.provider=='yahoo' else list(pd.read_csv(ROOT/cfg['universe']).ticker)
    if args.provider=='yahoo':provider=YahooSampleProvider(CACHE/'yahoo');start,end='2026-09-25','2026-10-02'
    elif args.provider=='csv':provider=CSVProvider(args.csv_dir);start,end=args.start,args.end
    else:provider=AlpacaProvider(CACHE/'alpaca',args.feed);start,end=args.start,args.end
    if not start or not end:raise ValueError('Historical provider requires --start and --end')
    frames=[];daily=[];unavailable=[]
    first_regular={'SPCX':'2026-06-12','DELL':'2018-12-28','GEV':'2024-04-02','SNDK':'2025-02-24'}
    for ticker in tickers+['SPY']:
        effective_start=max(start,first_regular.get(ticker,start))
        if effective_start>=end:
            unavailable.append(dict(ticker=ticker,reason='Listing after requested period',first_regular=effective_start));continue
        frames.append(provider.get_bars(ticker,effective_start,end))
        if args.provider=='yahoo':daily.append(provider.daily(ticker,'2025-01-01',end))
        print('sample',ticker,flush=True)
    raw=pd.concat(frames,ignore_index=True);bars=aggregate_minutes(raw)
    require_complete_sessions(bars)
    raw.to_csv(CACHE/'intraday_1m.csv',index=False);bars.to_pickle(CACHE/'intraday_5m.pkl')
    if daily:pd.concat(daily,ignore_index=True).to_csv(CACHE/'intraday_daily.csv',index=False)
    elif args.daily:pd.read_csv(args.daily).to_csv(CACHE/'intraday_daily.csv',index=False)
    else:raise ValueError('--daily requires matching daily history through intraday range')
    sessions=sorted(bars.Session.unique())
    if args.provider=='yahoo':train=p['sample_train'];validation=p['sample_validation']
    else:
        cut=int(len(sessions)*.75)
        if cut<1 or cut>=len(sessions):raise ValueError('Too few sessions')
        train=[sessions[0],sessions[cut-1]];validation=[sessions[cut],sessions[-1]]
    manifest=dict(provider=args.provider,feed=args.feed if args.provider=='alpaca' else None,acquired_at=now(),
        raw_sha256=sha(CACHE/'intraday_1m.csv'),bars_sha256=sha(CACHE/'intraday_5m.pkl'),daily_sha256=sha(CACHE/'intraday_daily.csv'),
        rows_1m=len(raw),rows_5m=len(bars),sessions=sessions,tickers=sorted(set(bars.Ticker)-{'SPY'}),unavailable=unavailable,train=train,validation=validation,
        historical_validation_eligible=args.provider!='yahoo',vwap='trade VWAP when supplied, otherwise minute typical-price approximation')
    write_json(OUT/'intraday_data_audit.json',manifest)
    if args.provider=='yahoo':
        SAMPLE.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(SAMPLE,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name in SAMPLE_FILES:z.write(CACHE/name,arcname=name)


def feature_cache(kind,end):
    inputs=[DAILY] if kind=='swing' else [CACHE/'intraday_5m.pkl',CACHE/'intraday_daily.csv']
    fingerprint=hashlib.sha256((''.join(sha(p) for p in inputs)+sha(HERE/'features.py')+str(end)).encode()).hexdigest()
    target=CACHE/f'{kind}_features_{fingerprint}.pkl'
    if target.exists():return pd.read_pickle(target)
    if kind=='swing':
        raw=pd.read_csv(DAILY,parse_dates=['Date']);raw=raw[raw.Date.le(end)]
        out=daily_features(raw)
    else:
        bars=pd.read_pickle(inputs[0]);bars=bars[bars.Session.le(end)]
        d=pd.read_csv(inputs[1],parse_dates=['Date']);d=d[d.Date.le(end)]
        out=intraday_features(bars,d)
    pd.to_pickle(out,target)
    return out


def periods(kind,cfg):
    if kind=='swing':return cfg['swing']['train'],cfg['swing']['validation']
    m=json.loads((OUT/'intraday_data_audit.json').read_text());return m['train'],m['validation']


def make_lab(kind,cfg,validation=False):
    train,test=periods(kind,cfg);period=test if validation else train
    f,names=feature_cache(kind,period[1]);p=cfg[kind]
    horizons=p['horizons'] if kind=='swing' else p['horizons_bars']
    cost=p['round_trip_cost'] if kind=='swing' else 2*sum(p[k] for k in ('half_spread_bps_per_side','slippage_bps_per_side','commission_bps_per_side'))/10000
    return Lab(f,kind,period,horizons,cost),names


def run_exploration(kind,cfg):
    if (OUT/'frozen_candidates.json').exists():raise RuntimeError('Candidates already frozen; exploration locked')
    lab,names=make_lab(kind,cfg)
    anchor=dict(feature='align_sma20_50' if kind=='swing' else 'distance_vwap',op='>',threshold=0.)
    summary,chosen=explore(lab,names,cfg,cfg[kind],anchor)
    summary.to_csv(OUT/f'{kind}_exploration_summary.csv',index=False)
    write_json(CACHE/f'{kind}_proposal.json',dict(candidates=chosen,feature_names=names,variants=len(summary),sessions=lab.session_count,protocol_sha256=sha(HERE/'protocol.json'),code_sha256={n:sha(HERE/n) for n in ('features.py','search.py','run.py','providers.py')}))
    print(kind,'FEATURES',len(names),'VARIANTS',len(summary),'FROZEN PROPOSALS',len(chosen),flush=True)


def freeze(cfg):
    payload=dict(frozen_at=now(),protocol_sha256=sha(HERE/'protocol.json'),universe_sha256=cfg['universe_sha256'],
        code_sha256={p.name:sha(p) for p in HERE.glob('*.py')},daily_sha256=sha(DAILY),
        intraday_data_audit_sha256=sha(OUT/'intraday_data_audit.json'),
        splits={kind:periods(kind,cfg) for kind in ('swing','intraday')},candidates=[])
    for kind in ('swing','intraday'):
        proposal=json.loads((CACHE/f'{kind}_proposal.json').read_text())
        if proposal['protocol_sha256']!=payload['protocol_sha256']:raise ValueError('Exploration used other protocol')
        if any(sha(HERE/n)!=v for n,v in proposal['code_sha256'].items()):raise ValueError('Code changed since exploration')
        payload[kind+'_search']=dict(feature_names=proposal['feature_names'],variants=proposal['variants'],sessions=proposal['sessions'],summary_sha256=sha(OUT/f'{kind}_exploration_summary.csv'))
        payload['candidates'].extend(proposal['candidates'])
    freeze_file(OUT/'frozen_candidates.json',payload)
    print('FROZEN',len(payload['candidates']),'candidates; validation has not run')


def validate(cfg):
    if (OUT/'validation_complete.json').exists():raise RuntimeError('Validation already consumed; do not retune/revalidate')
    frozen=load_frozen(OUT/'frozen_candidates.json')
    if frozen['daily_sha256']!=sha(DAILY):raise ValueError('Daily input changed')
    if frozen['intraday_data_audit_sha256']!=sha(OUT/'intraday_data_audit.json'):raise ValueError('Intraday source/split changed')
    audit=json.loads((OUT/'intraday_data_audit.json').read_text())
    if audit['bars_sha256']!=sha(CACHE/'intraday_5m.pkl'):raise ValueError('Aggregated input changed')
    if audit['raw_sha256']!=sha(CACHE/'intraday_1m.csv') or audit['daily_sha256']!=sha(CACHE/'intraday_daily.csv'):raise ValueError('Intraday input changed')
    annual=[];tickers=[];times=[];allrows=[]
    for kind in ('swing','intraday'):
        lab,_=make_lab(kind,cfg,True);rows=[]
        for candidate in [c for c in frozen['candidates'] if c['lab']==kind]:
            h=candidate['horizon'];mask=rule_mask(lab.f,candidate['rules']);ix=lab.select(mask,h)
            s=lab.stats(ix,h);t,dd=lab.details(ix,h);top=t.groupby('Ticker').Net.sum().nlargest(5).index.tolist()
            restricted=mask&~lab.f.Ticker.isin(top).to_numpy();ix5=lab.select(restricted,h);r5=lab.stats(ix5,h)
            yearly=t.groupby('Year').Net.mean();gross=t.Gross.to_numpy();stress=gross-2*lab.cost
            min_sample=s['trades']>=cfg[kind]['minimum_validation_trades'] and lab.session_count>=cfg[kind]['minimum_validation_sessions']
            if kind=='intraday':min_sample &= audit['historical_validation_eligible'] and frozen['intraday_search']['sessions']>=cfg[kind]['minimum_train_sessions_for_keep']
            keep=min_sample and (s['avg_net'] or -1)>0 and s['pf_net']>=1.1 and len(yearly)==len(set(lab.years)) and (yearly>0).all() and (r5['avg_net'] or -1)>0 and dd>=-.2
            if kind=='intraday':keep &= len(stress)>0 and stress.mean()>0
            row=dict(id=candidate['id'],lab=kind,horizon=h,conditions=candidate['conditions'],**s,max_drawdown=dd,
                top5_removed=';'.join(top),net_without_top5=r5['avg_net'],trades_without_top5=r5['trades'],
                worst_year=int(yearly.idxmin()) if len(yearly) else None,best_year=int(yearly.idxmax()) if len(yearly) else None,
                verdict='KEEP CANDIDATE' if keep else 'DROP',sample_sufficient=bool(min_sample))
            if kind=='intraday':
                row.update(avg_holding_minutes=float(t.Holding_Minutes.mean()) if len(t) else None,net_stress_cost_x2=float(stress.mean()) if len(stress) else None,status='historical' if audit['historical_validation_eligible'] else 'TECHNICAL_SAMPLE_ONLY')
                for bucket,g in t.groupby('Time_Bucket'):times.append(dict(id=candidate['id'],bucket=bucket,trades=len(g),avg_net=g.Net.mean()))
            for year,g in t.groupby('Year'):annual.append(dict(id=candidate['id'],lab=kind,year=year,trades=len(g),avg_gross=g.Gross.mean(),avg_net=g.Net.mean(),win_rate=g.Net.gt(0).mean()))
            for ticker,g in t.groupby('Ticker'):tickers.append(dict(id=candidate['id'],lab=kind,ticker=ticker,trades=len(g),net_contribution=g.Net.sum(),avg_net=g.Net.mean()))
            row['annual']=json.dumps(row['annual'],sort_keys=True);rows.append(row)
        # Empty but schema-bearing output is explicit when no exploration candidate qualifies.
        pd.DataFrame(rows,columns=None if rows else ['id','lab','horizon','trades','avg_net','pf_net','verdict']).to_csv(OUT/f'{kind}_validation.csv',index=False)
        allrows.extend(rows)
    for name,rows,cols in [('validation_annual',annual,['id','lab','year','trades','avg_gross','avg_net','win_rate']),('validation_ticker_concentration',tickers,['id','lab','ticker','trades','net_contribution','avg_net']),('intraday_time_buckets',times,['id','bucket','trades','avg_net'])]:
        pd.DataFrame(rows,columns=cols).to_csv(OUT/f'{name}.csv',index=False)
    write_json(OUT/'validation_complete.json',dict(completed_at=now(),frozen_sha256=sha(OUT/'frozen_candidates.json'),rows=len(allrows),note=cfg['holdout_caveat']))
    report(frozen,allrows,audit,cfg)


def report(frozen,rows,audit,cfg):
    lines=['# Research Engine V2 — exploration et validation séparées','',
        '**2024–2025 n’est pas historiquement vierge** : cette période a déjà été examinée en V1. Elle est strictement exclue de la sélection V2. Un KEEP reste un candidat, pas une validation finale indépendante.','',
        '## Exploration','',f"Swing : {frozen['swing_search']['variants']} variantes ; intraday : {frozen['intraday_search']['variants']} variantes. Les résultats train ne sont pas une preuve hors échantillon.",
        f"Gel : {frozen['frozen_at']}. Coûts swing 0,20 % ; intraday 0,09 % aller-retour, stress 0,18 %.",'',
        '| Candidat | Laboratoire | Horizon | Trades train | Moyenne nette train | PF train |','|---|---|---:|---:|---:|---:|']
    for c in frozen['candidates']:
        s=c['exploration'];lines.append(f"| {c['id']} | {c['lab']} | {c['horizon']} | {s['trades']} | {s['avg_net']:.4%} | {s['pf_net']:.3f} |")
    lines+=['','## Validation sans reconfiguration','','| Candidat | Trades | Moyenne nette | PF net | DD diagnostic | Sans top5 | Décision |','|---|---:|---:|---:|---:|---:|---|']
    fmt=lambda x:'n/a' if x is None else f'{x:.4%}'
    for r in rows:lines.append(f"| {r['id']} | {r['trades']} | {fmt(r['avg_net'])} | {r['pf_net']:.3f} | {r['max_drawdown']:.2%} | {fmt(r['net_without_top5'])} | {r['verdict']} |")
    lines+=['',f"Intraday réellement obtenu : {len(audit['sessions'])} séances, {audit['rows_1m']} lignes 1m, {len(audit['tickers'])} actions + SPY. Essai technique seulement ; aucune conclusion de robustesse pluriannuelle.",'',
        '## Limites','',
        '- Multiple testing : milliers de variantes, sans correction statistique conférant une preuve formelle ; train favorisé par sélection.',
        '- Snapshot actuel : survivorship bias accepté ; historiques courts et corrections de données V1 conservés.',
        '- Données daily ajustées Yahoo révisables ; coûts constants et fills Open/Close idéalisés.',
        '- Drawdown : sleeves fixes 1/100 par ticker, mark-to-market, sans réinvestissement ; diagnostic, pas sizing final.',
        '- Signal intraday au bar close, entrée bar suivant ; latence et spread réel non observés. VWAP Yahoo approximé depuis les minutes.',
        '- Le rang intraday de cet échantillon porte sur cinq titres, pas sur les cent. Provider complet nécessaire avant étude de production.',
        '- Aucun abonnement acheté, aucune clé disponible. Voir data_sources.md pour SIP historique et alternatives.',
        '- Aucun réglage après validation. Aucun broker, ordre, levier ou moteur portefeuille final. STOP.']
    (OUT/'decision.md').write_text('\n'.join(lines)+'\n')


def main():
    global OUT
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['sample','explore-swing','explore-intraday','freeze','validate','reproduce'])
    p.add_argument('--output',type=Path);p.add_argument('--provider',choices=['yahoo','csv','alpaca'],default='yahoo');p.add_argument('--csv-dir');p.add_argument('--start');p.add_argument('--end');p.add_argument('--daily');p.add_argument('--feed',choices=['sip','iex'],default='sip')
    args=p.parse_args();CACHE.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);cfg=config()
    if SAMPLE.exists():
        with zipfile.ZipFile(SAMPLE) as z:
            for name in SAMPLE_FILES:
                if not (CACHE/name).exists():(CACHE/name).write_bytes(z.read(name))
    if args.stage=='reproduce':
        if args.output is None or args.output.resolve()==OUT.resolve():raise ValueError('Use --output with a separate empty directory')
        source=OUT
        load_frozen(source/'frozen_candidates.json')
        if args.output.exists() and any(args.output.iterdir()):raise ValueError('Reproduction directory must be empty')
        args.output.mkdir(parents=True,exist_ok=True)
        for n in ('frozen_candidates.json','frozen_candidates.json.sha256','intraday_data_audit.json'):shutil.copyfile(source/n,args.output/n)
        OUT=args.output
        validate(cfg)
        for n in ('swing_validation.csv','intraday_validation.csv','validation_annual.csv','validation_ticker_concentration.csv','intraday_time_buckets.csv'):
            if sha(source/n)!=sha(OUT/n):raise AssertionError('Reproduction mismatch: '+n)
        print('Exact validation reproduction verified; no search run')
    elif args.stage=='sample':
        if (OUT/'frozen_candidates.json').exists():raise RuntimeError('Data/split locked after freeze')
        prepare(args,cfg)
    elif args.stage.startswith('explore-'):run_exploration(args.stage.split('-')[1],cfg)
    elif args.stage=='freeze':freeze(cfg)
    else:validate(cfg)

if __name__=='__main__':main()
