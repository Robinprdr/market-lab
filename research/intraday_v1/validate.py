"""Frozen validation first; 2026 is opened only for candidates already kept."""
import argparse
import json
import time
import numpy as np
import pandas as pd
from .common import CACHE,OUT,protocol,write,sha,cost
from .evaluate import paths,trade_rows,stats,concentration
from .search import verify_frozen,WINDOWS

COLUMNS=['candidate','ticker','session','signal_time','entry_time','exit_time','entry','exit','gross','net','stress_net','holding_minutes']

def collect(rules,stage,cfg):
    pieces={r['id']:[] for r in rules}
    for path in paths(stage):
        f=pd.read_parquet(path)
        for name,(lo,hi) in WINDOWS.items():f[name]=(f.Minute_ET.ge(lo)&f.Minute_ET.lt(hi)).astype(float)
        for rule in rules:pieces[rule['id']].append(trade_rows(f,rule,cfg))
        print(stage,path.stem,'evaluated',flush=True)
    return {r['id']:pd.concat(pieces[r['id']],ignore_index=True).sort_values(['entry_time','ticker']).reset_index(drop=True) if pieces[r['id']] else pd.DataFrame(columns=COLUMNS) for r in rules}

def summarize(trades,stage):
    records=[];annual=[];ticker=[];tod=[];holding=[]
    for rid,t in trades.items():
        row=dict(candidate=rid,stage=stage,**stats(t))
        if len(t):row.update(concentration(t))
        records.append(row)
        for year,g in t.groupby(pd.to_datetime(t.session).dt.year):annual.append(dict(candidate=rid,stage=stage,year=year,**stats(g)))
        for name,g in t.groupby('ticker'):ticker.append(dict(candidate=rid,stage=stage,ticker=name,contribution=float(g.net.sum()),pnl_fixed_notional=float(g.net.sum()*1000),**stats(g)))
        slot=pd.to_datetime(t.entry_time,utc=True).dt.tz_convert('America/New_York').dt.strftime('%H:%M')
        for name,g in t.groupby(slot):tod.append(dict(candidate=rid,stage=stage,entry_time_et=name,**stats(g)))
        for name,g in t.groupby('holding_minutes'):holding.append(dict(candidate=rid,stage=stage,minutes=name,**stats(g)))
    return records,annual,ticker,tod,holding

def append_table(name,rows,stage,columns):
    p=OUT/name
    previous=pd.read_csv(p) if p.exists() else pd.DataFrame(columns=columns)
    if 'stage' in previous:previous=previous[previous.stage.ne(stage)]
    current=pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)
    pd.concat([previous,current],ignore_index=True).to_csv(p,index=False)

def portfolio(trades,stage,cfg,candidate='combined'):
    """Fixed $1k notionals, five slots, cash financed, five-minute mark-to-market."""
    if trades.empty:return dict(stage=stage,trades=0,capital=cfg['portfolio']['capital'],ending_equity=cfg['portfolio']['capital'],total_return=0.,max_drawdown=0.,win_rate=None,pf_net=None)
    trades=trades.copy();trades.entry_time=pd.to_datetime(trades.entry_time,utc=True);trades.exit_time=pd.to_datetime(trades.exit_time,utc=True)
    entry={date:g for date,g in trades.groupby('entry_time')};positions={};accepted=[];cash=cfg['portfolio']['capital'];peak=cash;dd=0.;curve=[]
    notional=cfg['portfolio']['notional'];half_cost=notional*cost(cfg)/2
    for path in paths(stage):
        prices=pd.read_parquet(path,columns=['Ticker','Bar_End','Close'])
        close={date:dict(zip(g.Ticker,g.Close)) for date,g in prices.groupby('Bar_End')}
        times=sorted(set(close)|{x for x in entry if str(x.date())[:7]==path.stem})
        for timestamp in times:
            for ticker,p in list(positions.items()):
                if p['exit_time']==timestamp:
                    cash+=p['shares']*p['exit']-half_cost;accepted.append(p['row']);del positions[ticker]
            marks=close.get(timestamp,{})
            for ticker,p in positions.items():
                price=marks.get(ticker)
                if price is not None and np.isfinite(price):p['mark']=price
            # Exits/mark previous bar close precede next bar opening fills at this timestamp.
            for row in entry.get(timestamp,pd.DataFrame()).itertuples(index=False):
                if row.ticker in positions or len(positions)>=cfg['portfolio']['maximum_positions'] or cash<notional+half_cost:continue
                cash-=notional+half_cost
                positions[row.ticker]=dict(shares=notional/row.entry,mark=row.entry,exit=row.exit,exit_time=row.exit_time,row=row._asdict())
            equity=cash+sum(p['shares']*p['mark'] for p in positions.values());peak=max(peak,equity);dd=min(dd,equity/peak-1)
            curve.append(dict(stage=stage,time=timestamp,equity=equity,cash=cash,positions=len(positions)))
        if positions:raise AssertionError('Overnight portfolio position')
    selected=pd.DataFrame(accepted);pd.DataFrame(curve).to_parquet(CACHE/f'portfolio_{candidate}_{stage}.parquet',index=False)
    selected.to_csv(OUT/f'portfolio_trades_{candidate}_{stage}.csv',index=False)
    result=dict(stage=stage,capital=cfg['portfolio']['capital'],ending_equity=cash,total_return=cash/cfg['portfolio']['capital']-1,max_drawdown=dd,**stats(selected))
    # signal_drawdown is a sum of equal-notional signal returns; this field is the actual MTM portfolio drawdown.
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['validation','final']);args=parser.parse_args()
    start=time.monotonic();cfg=protocol();frozen=verify_frozen();rules=frozen['candidates']
    if args.stage=='final':
        gate=OUT/'validation_verdicts.json'
        if not gate.exists():raise SystemExit('Validation verdicts must exist before opening final holdout')
        verdicts=json.loads(gate.read_text())
        if verdicts['frozen_sha256']!=sha(OUT/'frozen_intraday_candidates.json'):raise ValueError('Different validation freeze')
        rules=[r for r in rules if verdicts['verdicts'].get(r['id'])=='KEEP_CANDIDATE']
    trades=collect(rules,args.stage,cfg) if rules else {}
    records,annual,ticker,tod,holding=summarize(trades,args.stage);decisions={}
    date_rows=[]
    for rid,t in trades.items():
        for day,g in t.groupby('session'):date_rows.append(dict(candidate=rid,stage=args.stage,session=day,net_contribution=float(g.net.sum()),**stats(g)))
    append_table('date_contribution.csv',date_rows,args.stage,['candidate','stage','session','net_contribution','trades'])
    pd.concat(list(trades.values()),ignore_index=True).to_csv(OUT/f'{args.stage}_trades.csv',index=False) if trades else pd.DataFrame(columns=COLUMNS).to_csv(OUT/f'{args.stage}_trades.csv',index=False)
    for row in records:
        rid=row['candidate'];t=trades[rid];yearly=[x for x in annual if x['candidate']==rid]
        if args.stage=='validation':
            keep=(row['trades']>=cfg['validation_min_trades'] and row['pf_net'] is not None and row['pf_net']>=cfg['validation_min_pf'] and row['average_net']>0 and row['stress_average_net']>0 and len(yearly)==2 and all(x['average_net']>0 for x in yearly) and row.get('top_ticker_share',1)<=cfg['validation_top_ticker_share'] and row.get('remove_top5_average_net') is not None and row['remove_top5_average_net']>0)
            row['verdict']='KEEP_CANDIDATE' if keep else 'DROP'
        else:
            passing=(row['trades']>=cfg['final_min_trades'] and row['pf_net'] is not None and row['pf_net']>=cfg['final_min_pf'] and row['average_net']>0 and row['stress_average_net']>0 and row.get('remove_top5_average_net') is not None and row['remove_top5_average_net']>0)
            row['verdict']='PASS' if passing else 'WEAK' if row['average_net'] is not None and row['average_net']>0 else 'FAIL'
        decisions[rid]=row['verdict'];t.to_parquet(CACHE/f'{rid}_{args.stage}_trades.parquet',index=False)
    target='validation_2024_2025.csv' if args.stage=='validation' else 'final_2026.csv'
    pd.DataFrame(records,columns=list(records[0]) if records else ['candidate','stage','trades','average_net','pf_net','verdict']).to_csv(OUT/target,index=False)
    for name,rows,columns in [('annual_results.csv',annual,['candidate','stage','year','trades','average_net']),('ticker_contribution.csv',ticker,['candidate','stage','ticker','contribution','trades']),('time_of_day.csv',tod,['candidate','stage','entry_time_et','trades']),('holding_duration.csv',holding,['candidate','stage','minutes','trades'])]:append_table(name,rows,args.stage,columns)
    write(OUT/f'{args.stage}_verdicts.json',dict(frozen_sha256=sha(OUT/'frozen_intraday_candidates.json'),verdicts=decisions,seconds=time.monotonic()-start,skipped_reason='No frozen candidates' if not rules else None))
    if args.stage=='validation':print('VALIDATION COMPLETE',decisions,flush=True);return
    port=[]
    for r in rules:port.append(dict(candidate=r['id'],**portfolio(trades[r['id']],'final',cfg,r['id'])))
    pd.DataFrame(port,columns=list(port[0]) if port else ['candidate','stage','trades','total_return','max_drawdown']).to_csv(OUT/'portfolio_summary.csv',index=False)
    report(cfg,frozen,records,port);print('FINAL COMPLETE',decisions,flush=True)

def report(cfg,frozen,final,port):
    search=json.loads((OUT/'search_manifest.json').read_text());data=json.loads((OUT/'data_manifest.json').read_text());quality=pd.read_csv(OUT/'data_quality.csv')
    integrity=json.loads((OUT/'cache_integrity.json').read_text())
    included_quality=quality[quality.included_in_research.fillna(False)]
    train=pd.read_csv(OUT/'exploration_summary.csv');validation=pd.read_csv(OUT/'validation_2024_2025.csv')
    verdict='PASS' if any(r['verdict']=='PASS' for r in final) else 'WEAK' if any(r['verdict']=='WEAK' for r in final) else 'FAIL'
    best=train.sort_values('average_net',ascending=False).head(5)[['id','family','trades','average_net','pf_net']].to_string(index=False)
    diagnostic=''
    vp=OUT/'validation_trades.csv'
    if vp.exists():
        vt=pd.read_csv(vp)
        for rid,t in vt.groupby('candidate'):
            totals=t.groupby('session').net.sum().sort_values(ascending=False);best=totals.index[0];rest=t[t.session.ne(best)]
            diagnostic+=f'Validation {rid}: best date {best}, {int(t.session.eq(best).sum())} trades, net contribution {float(totals.iloc[0]):.6f} in summed return units; excluding that date, {len(rest)} trades with mean net {float(rest.net.mean())*100:.4f}%. This is a diagnostic, not a new rule or threshold.\n'
    text=f'''# Intraday Research V1 — {verdict}

Protocol fixed before search: exploration 2018–2023; validation 2024–2025; final 2026-01-01 to {cfg['final'][1]}. LONG only, regular session only, signal at five-minute close, next bar open, same-day fixed horizons 15/30/60/90/120 minutes or EOD. Fixed holds require their full length; signals too near close are ineligible for that horizon.

Data: SIP, split adjusted, symbol asof {cfg['symbol_asof']}; {data['regular_bars']:,} cached regular minute bars, of which {integrity['usable_regular_bars']:,} belong to the retained company identities; {integrity['excluded_prefix_bars']:,} predecessor/when-issued bars excluded; {data['disk_bytes']:,} source cache bytes; download {data['seconds']:.1f}s. Nonexistent listing periods are not fabricated. Current Top100 snapshot introduces survivorship bias; some present-day symbols have unusual history/renaming. See availability.csv and data_quality.csv.

Features use scheduled bars, leave holes empty, never compress time. All prior-day context is strictly before the session. OR is unavailable until its interval closes; VWAP uses only observed minute price/volume; RVol uses prior same-slot sessions. Cross-sectional ranks use only contemporaneously observed members. Missing or incomplete holding intervals make outcomes unavailable, not zero. No orders were sent and no trading endpoints were used.

Search: {search['variants']} variants; {search['families']} families; {search['thresholds']} distinct tested threshold predicates; one to four simple predicates. Maximum ten frozen candidates; predeclared frequency/net/stress/annual/concentration gates. Multiple testing makes exploration results selection-biased, not evidence of robustness. No dynamic exits were added.

Costs: {cost(cfg)*10000:.0f}bp round trip (3.5bp commission + 1bp half-spread + 2.5bp slippage per side), stress {2*cost(cfg)*10000:.0f}bp. LONG gross = exit/entry - 1; fixed costs are deducted on entry notional. Bar ranges are a liquidity proxy, not a measured bid/ask spread. No prices were substituted across holes.

Frozen candidates: {len(frozen['candidates'])}. Validation verdicts are in validation_2024_2025.csv. Final evaluated candidates: {len(final)}. Final verdict: **{verdict}**. If no candidate is kept, the final holdout performance is not opened and final files are intentionally empty. This is a completed rejection, not permission to tune new filters on 2024–2026.

{diagnostic}

Known adjustment exception: RTX on 2020-04-03 shows a -70.26% split-adjusted overnight discontinuity. No overnight PnL is measured, but nearby daily context requires a separate corporate-action audit. It was flagged, not repaired or used to retune this experiment. Historical quote/VWAP precision also varies by ticker/year; see availability.csv.

Performance timing: the minute download wall time includes interruptions and resumptions; its final resumed run took {data['seconds_current_run']:.1f}s. Feature elapsed time includes waiting for source partitions and overlaps download; it is not additive with download. Search computation took {search['seconds']:.1f}s.

Top raw exploration means (may fail minimum sample/stress/concentration gates):

```
{best}
```

Quality: {len(quality):,} diagnostics. Within retained company-identity periods: {int(included_quality.missing_minutes.fillna(0).sum()):,} missing source minutes and {int(included_quality.invalid_bars.fillna(0).sum()):,} invalid bars. Partial listing years and source exceptions are explicitly retained. Equity drawdown in portfolio_summary is five-minute mark-to-market; signal_drawdown is an equal-notional cumulative signal sum and is not a portfolio percentage. Portfolio uses $10k cash, $1k fixed notional, maximum five simultaneous positions, no leverage; fractional shares are a research assumption.

Limits: {'. '.join(cfg['limits'])}. Cached adjusted histories are provider snapshots, not a reconstructed historical universe. Price-only data do not measure opening latency or exact execution. Final 2026 is isolated from this search but earlier research already observed parts of these calendar years. A research PASS would require prospective/paper confirmation, not deployment.

No main merge; no strategy modifications; no brokerage trading. Stop after this mission.
'''
    (OUT/'decision.md').write_text(text)

if __name__=='__main__':main()
