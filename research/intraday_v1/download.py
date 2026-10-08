"""Resumable SIP-only data acquisition, with bounded memory and private headers."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import os
import threading
import time
import numpy as np
import pandas as pd
import requests
from bot.calendar import exchange,last_complete_session
from .common import CACHE,OUT,UNIVERSE,initialize,protocol,write,sha

lock=threading.Lock();next_request=0.;local=threading.local()

def api(args):
    global next_request
    if not hasattr(local,'session'):local.session=requests.Session()
    headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']}
    for attempt in range(5):
        with lock:
            delay=max(0.,next_request-time.monotonic());next_request=time.monotonic()+delay+.36
        if delay:time.sleep(delay)
        try:
            response=local.session.get('https://data.alpaca.markets/v2/stocks/bars',params=args,headers=headers,timeout=45)
        except requests.RequestException:
            if attempt==4:raise RuntimeError('Alpaca transport failed; request details suppressed') from None
            time.sleep(2**attempt);continue
        if response.status_code in (429,500,502,503,504):
            time.sleep(min(30,2**attempt+2));continue
        if response.status_code!=200:raise RuntimeError(f'Alpaca data HTTP {response.status_code}; body suppressed')
        return response.json()
    raise RuntimeError('Alpaca retries exhausted')

def fetch(ticker,start,end,timeframe='1Min',adjustment='split'):
    provider_symbol={'BRK-B':'BRK.B'}.get(ticker,ticker)
    args=dict(symbols=provider_symbol,start=start,end=end,timeframe=timeframe,feed='sip',adjustment=adjustment,sort='asc',limit=10000,asof='2026-10-02')
    rows=[];pages=0;tokens=set()
    while True:
        obj=api(args);pages+=1;rows.extend((obj.get('bars') or {}).get(provider_symbol,[]))
        token=obj.get('next_page_token')
        if not token:break
        if token in tokens:raise ValueError('Repeated pagination token')
        tokens.add(token);args['page_token']=token
    if not rows:return pd.DataFrame(),pages
    f=pd.DataFrame(rows).rename(columns=dict(t='Date',o='Open',h='High',l='Low',c='Close',v='Volume',vw='VWAP',n='Trades'))
    f.Date=pd.to_datetime(f.Date,utc=True);f['Ticker']=ticker
    # Provider bounds may be inclusive; explicitly enforce the requested half-open range.
    f=f[f.Date.ge(pd.Timestamp(start))&f.Date.lt(pd.Timestamp(end))].copy()
    if f.Date.duplicated().any():raise ValueError('Duplicate source timestamps')
    return f.sort_values('Date').reset_index(drop=True),pages

def schedule(year,end):
    cal=exchange(f'{year}-01-01')
    import exchange_calendars as xc
    return xc.get_calendar('XNYS',start=f'{year}-01-01',end=end).schedule

def quality(f,ticker,year,sch):
    if f.empty:return f,[dict(ticker=ticker,year=year,session='',status='NO_DATA',source_bars=0,regular_bars=0,missing_minutes=0,invalid_bars=0)]
    ny=f.Date.dt.tz_convert('America/New_York');f['Session']=ny.dt.strftime('%Y-%m-%d')
    diagnostics=[];parts=[]
    days={day:g for day,g in f.groupby('Session',sort=False)}
    first=min(days);last=max(days)
    for session,row in sch.iterrows():
        day=session.date().isoformat()
        if day<first or day>last:continue
        opened,closed=row['open'],row['close'];g=days.get(day,f.iloc[:0]).copy()
        source=len(g);g=g[g.Date.ge(opened)&g.Date.lt(closed)]
        expected=pd.date_range(opened,closed,freq='1min',inclusive='left')
        vals=g[['Open','High','Low','Close','Volume']].to_numpy(float)
        valid=np.isfinite(vals).all(axis=1)&(vals[:,:4]>0).all(axis=1)&(vals[:,4]>=0)
        valid &= (g.High>=g[['Open','Low','Close']].max(axis=1)).to_numpy()&(g.Low<=g[['Open','High','Close']].min(axis=1)).to_numpy()
        valid &= np.isfinite(g.VWAP.to_numpy(float)) & g.VWAP.gt(0).to_numpy()
        valid &= g.Date.dt.second.eq(0).to_numpy()&g.Date.dt.microsecond.eq(0).to_numpy()
        diagnostics.append(dict(ticker=ticker,year=year,session=day,status='OK' if valid.all() and len(g)==len(expected) else 'GAPS_OR_INVALID',source_bars=source,regular_bars=len(g),expected_minutes=len(expected),missing_minutes=len(expected.difference(g.Date)),invalid_bars=int((~valid).sum())))
        g=g[valid].copy();g['Session_Open']=opened;g['Session_Close']=closed;parts.append(g)
    if not diagnostics:diagnostics=[dict(ticker=ticker,year=year,session='',status='NO_REGULAR_DATA',source_bars=len(f),regular_bars=0,missing_minutes=0,invalid_bars=0)]
    return pd.concat(parts,ignore_index=True) if parts else f.iloc[:0],diagnostics

def partition(ticker,year,end):
    target=CACHE/'1m'/ticker/f'{year}.parquet';manifest=target.with_suffix('.json')
    if target.exists() and manifest.exists():
        info=__import__('json').loads(manifest.read_text())
        expected=min(pd.Timestamp(f'{year+1}-01-01',tz='UTC'),pd.Timestamp(end)).isoformat()
        if info['end']!=expected or target.stat().st_size!=info['bytes']:raise ValueError('Stale or damaged cache partition')
        if info.get('sha256') and info['sha256']!=sha(target):raise ValueError('Cache integrity mismatch')
        return dict(ticker=ticker,year=year,cached=True,**info)
    started=time.monotonic();final=min(pd.Timestamp(f'{year+1}-01-01',tz='UTC'),pd.Timestamp(end))
    f,pages=fetch(ticker,f'{year}-01-01T00:00:00Z',final.isoformat())
    sch=schedule(year,final.date().isoformat());regular,diagnostics=quality(f,ticker,year,sch)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.part.parquet');regular.to_parquet(temporary,index=False,row_group_size=10000);temporary.replace(target)
    pd.DataFrame(diagnostics).to_csv(target.with_suffix('.quality.csv'),index=False)
    info=dict(source_bars=len(f),regular_bars=len(regular),pages=pages,seconds=time.monotonic()-started,bytes=target.stat().st_size,end=final.isoformat(),feed='sip',adjustment='split',asof='2026-10-02')
    info['sha256']=sha(target);write(manifest,info);return dict(ticker=ticker,year=year,cached=False,**info)

def daily(ticker,end):
    target=CACHE/'daily'/f'{ticker}.parquet'
    if target.exists():return
    frame,pages=fetch(ticker,'2017-01-01T00:00:00Z',end,'1Day')
    if not frame.empty:frame['Session']=frame.Date.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_suffix('.part.parquet');frame.to_parquet(temporary,index=False);temporary.replace(target)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    if not all(os.environ.get(x) for x in ('APCA_API_KEY_ID','APCA_API_SECRET_KEY')):raise SystemExit('Alpaca credentials absent')
    cfg=initialize(last_complete_session());end=exchange(cfg['final'][1]).schedule.loc[pd.Timestamp(cfg['final'][1]),'close'].isoformat()
    tickers=pd.read_csv(UNIVERSE).ticker.tolist()+['SPY'];jobs=[(t,y) for t in tickers for y in range(2018,2027)]
    start=time.monotonic();records=[];failures=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(partition,t,y,end):(t,y) for t,y in jobs}
        for future in as_completed(futures):
            try:row=future.result()
            except Exception as exc:
                failures.append(dict(ticker=futures[future][0],year=futures[future][1],error_type=type(exc).__name__))
                write(OUT/'download_failure.json',failures)
                print('partition failed',futures[future][0],futures[future][1],type(exc).__name__,flush=True)
                continue
            records.append(row)
            if len(records)%10==0:print('download partitions',len(records),'/',len(jobs),'regular bars',sum(r['regular_bars'] for r in records),flush=True)
    if failures:raise RuntimeError('Some partitions failed; rerun to resume completed cache; credentials suppressed')
    for i,ticker in enumerate(tickers):
        daily(ticker,end)
        if (i+1)%10==0:print('daily contexts',i+1,flush=True)
    qualities=[pd.read_csv(p) for p in (CACHE/'1m').glob('*/*.quality.csv')]
    pd.concat(qualities,ignore_index=True).to_csv(OUT/'data_quality.csv',index=False)
    pd.DataFrame(records).to_csv(OUT/'download_partitions.csv',index=False)
    began=min(p.stat().st_mtime-__import__('json').loads(p.with_suffix('.json').read_text())['seconds'] for p in (CACHE/'1m').glob('*/*.parquet') if not p.name.endswith('.part.parquet'))
    (OUT/'download_failure.json').unlink(missing_ok=True)
    write(OUT/'data_manifest.json',dict(seconds=time.time()-began,seconds_current_run=time.monotonic()-start,pages=sum(r['pages'] for r in records),regular_bars=sum(r['regular_bars'] for r in records),source_bars=sum(r['source_bars'] for r in records),disk_bytes=sum(r['bytes'] for r in records),tickers=len(tickers)-1,end=end,partitions=len(jobs)))
    print('DOWNLOAD COMPLETE',flush=True)

if __name__=='__main__':main()
