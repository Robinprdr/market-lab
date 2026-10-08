"""Bounded per-ticker features; gaps remain on the scheduled five-minute grid."""
import argparse
import json
import time
import numpy as np
import pandas as pd
from .common import CACHE,OUT,UNIVERSE,HERE,protocol,write,sha

CONTEXT=['return_5','return_10','return_20','distance_sma20','distance_sma50','atr_pct_14','rs_spy_20','spy_distance_sma50']

def aggregate(raw):
    if raw.empty:return pd.DataFrame()
    if raw.Date.duplicated().any():raise ValueError('Duplicate minute bars')
    raw=raw.sort_values('Date').copy()
    raw['Slot']=((raw.Date-raw.Session_Open).dt.total_seconds()//300).astype(int)
    raw['DollarVolume']=raw.Volume*raw.VWAP
    raw['ValidMinute']=np.isfinite(raw[['Open','High','Low','Close','Volume','VWAP']].to_numpy(float)).all(axis=1)&raw.VWAP.gt(0).to_numpy()
    group=raw.groupby(['Session','Slot'],sort=True)
    bars=group.agg(Open=('Open','first'),High=('High','max'),Low=('Low','min'),Close=('Close','last'),Volume=('Volume','sum'),DollarVolume=('DollarVolume','sum'),Minute_Count=('ValidMinute','sum'))
    parts=[]
    for day,g in raw.groupby('Session',sort=True):
        opened,closed=g.Session_Open.iloc[0],g.Session_Close.iloc[0]
        index=pd.RangeIndex(int((closed-opened).total_seconds()//300),name='Slot')
        f=bars.loc[day].reindex(index).reset_index();f['Session']=day;f['Date']=opened+pd.to_timedelta(f.Slot*5,unit='min')
        f['Bar_End']=f.Date+pd.Timedelta(minutes=5);f['Session_Open']=opened;f['Session_Close']=closed
        f['Complete']=f.Minute_Count.eq(5)
        f.loc[~f.Complete,['Open','High','Low','Close','Volume','DollarVolume']]=np.nan
        f['Feature_Eligible']=f.Complete.cummin();f['Ticker']=g.Ticker.iloc[0];parts.append(f)
    return pd.concat(parts,ignore_index=True)

def intraday(bars):
    if bars.empty:return bars
    f=bars.sort_values('Date').reset_index(drop=True).copy();group=f.groupby('Session',sort=False);c=f.Close
    def transform(s,fn):return s.groupby(f.Session,sort=False).transform(fn)
    def shift(s,n=1):return s.groupby(f.Session,sort=False).shift(n)
    def change(s,n=1):return s/shift(s,n)-1
    for n in (5,10,15,30,60):f[f'return_{n}m']=change(c,n//5)
    first=group.Open.transform(lambda x:x.iloc[0]);f['return_open']=c/first-1;f['acceleration']=f.return_5m-shift(f.return_5m)
    f['VWAP']=transform(f.DollarVolume,lambda x:x.cumsum())/transform(f.Volume,lambda x:x.cumsum()).replace(0,np.nan)
    f['distance_vwap']=c/f.VWAP-1;f['slope_vwap']=change(f.VWAP,3)
    above=c.gt(f.VWAP);f['vwap_reclaim']=(above & ~shift(above).fillna(False).astype(bool) & f.Slot.gt(0)).astype(float)
    f['vwap_hold3']=transform(above.astype(float),lambda x:x.rolling(3).min())
    for n in (5,15,30,60):
        hi=transform(f.High.where(f.Slot.lt(n//5)),lambda x:x.cummax().ffill()).where((f.Slot+1)*5>=n)
        lo=transform(f.Low.where(f.Slot.lt(n//5)),lambda x:x.cummin().ffill()).where((f.Slot+1)*5>=n)
        f[f'or{n}_distance']=c/hi-1;f[f'or{n}_range']=(hi-lo)/first
        f[f'or{n}_breakout']=(c.gt(hi)&shift(c).le(shift(hi))).where(hi.notna()).astype(float)
    f['HOD']=group.High.cummax();f['LOD']=group.Low.cummin();f['distance_hod']=c/f.HOD-1
    f['new_high']=f.High.gt(shift(f.HOD)).astype(float);f['session_range']=(f.HOD-f.LOD)/first
    f['range_position']=(c-f.LOD)/(f.HOD-f.LOD).replace(0,np.nan)
    f['volume_acceleration']=f.Volume/shift(f.Volume).replace(0,np.nan)-1
    f['volume_breakout']=f.Volume/transform(shift(f.Volume),lambda x:x.rolling(3).mean()).replace(0,np.nan)
    history=f.groupby('Slot',sort=False).Volume
    mean=history.transform(lambda s:s.shift().rolling(20,min_periods=10).mean())
    std=history.transform(lambda s:s.shift().rolling(20,min_periods=10).std())
    f['relative_volume']=f.Volume/mean.replace(0,np.nan);f['volume_z20']=(f.Volume-mean)/std.replace(0,np.nan)
    # Rank of current observed volume among the trailing 20 previous sessions plus itself.
    f['volume_percentile']=history.transform(lambda s:s.rolling(21,min_periods=11).rank(pct=True))
    emas={n:transform(c,lambda x,n=n:x.ewm(span=n,adjust=False,min_periods=n).mean()) for n in (9,20,50)}
    for n,e in emas.items():f[f'distance_ema{n}']=c/e-1
    f['align_ema9_20']=emas[9]/emas[20]-1;f['align_ema20_50']=emas[20]/emas[50]-1;f['ema_slope']=change(emas[9],3)
    spread=(f.High-f.Low).replace(0,np.nan);f['clv']=(c-f.Low)/spread;f['body_range']=(c-f.Open)/spread
    up=c.gt(f.Open);resets=(~up).groupby(f.Session).cumsum()
    f['green_streak']=up.groupby([f.Session,resets]).cumsum().astype(float)
    f['range_expansion']=spread/transform(shift(spread),lambda x:x.rolling(6).mean());f['range_compression']=1/f.range_expansion
    f['impulse_30m']=transform(f.return_open,lambda x:x.rolling(6,min_periods=1).max())
    f['range_pct']=(f.High-f.Low)/f.Close;f['Minute_ET']=570+(f.Slot+1)*5
    return f.replace([np.inf,-np.inf],np.nan)

def attach_daily(f,context):
    if f.empty:return f
    day=context[['Session']+CONTEXT].rename(columns={'Session':'Daily_Date',**{k:'daily_'+k for k in CONTEXT}}).copy()
    day.Daily_Date=pd.to_datetime(day.Daily_Date);f=f.copy();f['Join_Date']=pd.to_datetime(f.Session)
    f=pd.merge_asof(f.sort_values('Join_Date'),day.sort_values('Daily_Date'),left_on='Join_Date',right_on='Daily_Date',allow_exact_matches=False,direction='backward')
    if (f.Daily_Date>=f.Join_Date).any():raise AssertionError('Noncausal daily feature')
    return f.drop(columns='Join_Date').sort_values('Date').reset_index(drop=True)

def cross_section(f):
    f=f.copy();stocks=~f.Ticker.eq('SPY');spy=f[~stocks].set_index('Date')
    for n in (5,15,30,60):
        k=f'return_{n}m';f[f'rs_spy_{n}m']=f[k]-f.Date.map(spy[k])
        f[f'rs_universe_{n}m']=f[k]-f.Date.map(f[stocks].groupby('Date')[k].median())
        f[f'rank_{n}m']=f[stocks].groupby('Date')[k].rank(pct=True)
    return f[stocks].sort_values(['Ticker','Date']).reset_index(drop=True)

def feature_columns():
    return ['return_'+str(n)+'m' for n in (5,10,15,30,60)]+['return_open','acceleration','distance_vwap','slope_vwap','vwap_reclaim','vwap_hold3']+['or'+str(n)+'_'+k for n in (5,15,30,60) for k in ('distance','range','breakout')]+['distance_hod','new_high','session_range','range_position','volume_acceleration','volume_breakout','relative_volume','volume_z20','volume_percentile']+['distance_ema'+str(n) for n in (9,20,50)]+['align_ema9_20','align_ema20_50','ema_slope','clv','body_range','green_streak','range_expansion','range_compression','impulse_30m']+['daily_'+k for k in CONTEXT]+[k+'_'+str(n)+'m' for n in (5,15,30,60) for k in ('rs_spy','rs_universe','rank')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-for-download',action='store_true');args=parser.parse_args()
    cfg=protocol();start=time.monotonic();tickers=pd.read_csv(UNIVERSE).ticker.tolist()+['SPY']
    from research.research_v2.features import daily_features
    overrides=json.loads((HERE/'data_overrides.json').read_text())
    daily_parts=[]
    for t in tickers:
        daily_path=CACHE/'daily'/f'{t}.parquet'
        while args.wait_for_download and not daily_path.exists():time.sleep(10)
        d=pd.read_parquet(daily_path)
        if not d.empty and t in overrides:d=d[d.Session.ge(overrides[t]['start'])]
        if not d.empty:daily_parts.append(d)
    daily=pd.concat(daily_parts,ignore_index=True)
    daily['Date']=pd.to_datetime(daily.Session);ctx,_=daily_features(daily)
    for j,t in enumerate(tickers):
        context=ctx[ctx.Ticker.eq(t)];previous=pd.DataFrame()
        for year in range(2018,2027):
            target=CACHE/'ticker_features'/t/f'{year}.parquet';target.parent.mkdir(parents=True,exist_ok=True)
            raw_path=CACHE/'1m'/t/f'{year}.parquet'
            while args.wait_for_download and not raw_path.with_suffix('.json').exists():time.sleep(10)
            raw=pd.read_parquet(raw_path)
            if not raw.empty and t in overrides:raw=raw[raw.Session.ge(overrides[t]['start'])]
            bars=aggregate(raw)
            if bars.empty:bars.to_parquet(target,index=False);continue
            fingerprint={'raw':sha(raw_path),'code':sha(__file__),'overrides':sha(HERE/'data_overrides.json'),'daily':sha(CACHE/'daily'/f'{t}.parquet')}
            meta=target.with_suffix('.json')
            if not target.exists() or not meta.exists() or json.loads(meta.read_text())!=fingerprint:
                joined=pd.concat([previous,bars],ignore_index=True);enriched=attach_daily(intraday(joined),context)
                enriched=enriched[enriched.Date.dt.year.eq(year)]
                enriched.to_parquet(target,index=False,row_group_size=10000);write(meta,fingerprint)
            days=bars.Session.unique()[-25:];previous=bars[bars.Session.isin(days)].copy()
        if (j+1)%5==0:print('feature tickers',j+1,'/',len(tickers),flush=True)
    months=pd.period_range('2018-01',cfg['final'][1][:7],freq='M');rows=0
    for i,month in enumerate(months):
        parts=[]
        for t in tickers:
            path=CACHE/'ticker_features'/t/f'{month.year}.parquet'
            # Predicate reads only this month, not an entire multi-year panel.
            try:f=pd.read_parquet(path,filters=[('Session','>=',str(month)+'-01'),('Session','<=',str(month.end_time.date()))])
            except (__import__('pyarrow').ArrowInvalid,__import__('pyarrow').ArrowNotImplementedError):f=pd.DataFrame()
            if not f.empty:parts.append(f)
        frame=cross_section(pd.concat(parts,ignore_index=True));rows+=len(frame)
        target=CACHE/'features'/f'{month}.parquet';target.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(target,index=False,row_group_size=10000)
        if (i+1)%12==0:print('feature months',i+1,'/',len(months),flush=True)
    write(OUT/'feature_manifest.json',dict(seconds=time.monotonic()-start,rows=rows,features=feature_columns(),count=len(feature_columns()),source='1m SIP split-adjusted',timeframe_minutes=5))
    print('FEATURES COMPLETE',flush=True)

if __name__=='__main__':main()
