"""Interpretable features. All rolling operations are backward looking."""
import numpy as np
import pandas as pd


def daily_features(raw):
    parts=[]; names=[]
    for ticker,g in raw.groupby('Ticker',sort=True):
        g=g.sort_values('Date').copy(); c=g.Close; prev=c.shift(); x={}
        for n in (1,2,3,5,10,20,40): x[f'return_{n}']=c.pct_change(n,fill_method=None)
        x['acceleration']=x['return_5']-(c.shift(5)/c.shift(10)-1)
        for n in (10,20,50,100):
            ma=c.rolling(n).mean();x[f'distance_sma{n}']=c/ma-1
        x['align_sma20_50']=c.rolling(20).mean()/c.rolling(50).mean()-1
        x['slope_sma20']=c.rolling(20).mean().pct_change(5,fill_method=None)
        for n in (9,20,50):
            ema=c.ewm(span=n,adjust=False,min_periods=n).mean();x[f'distance_ema{n}']=c/ema-1
        x['align_ema9_20']=c.ewm(span=9,adjust=False,min_periods=9).mean()/c.ewm(span=20,adjust=False,min_periods=20).mean()-1
        tr=pd.concat([g.High-g.Low,(g.High-prev).abs(),(g.Low-prev).abs()],axis=1).max(axis=1)
        for n in (5,14,20): x[f'atr_pct_{n}']=tr.rolling(n).mean()/c
        for n in (5,20):x[f'realized_vol_{n}']=x['return_1'].rolling(n).std()
        for n in (5,10,20):x[f'volume_ratio_{n}']=g.Volume/g.Volume.rolling(n).mean()
        x['volume_z20']=(g.Volume-g.Volume.rolling(20).mean())/g.Volume.rolling(20).std().replace(0,np.nan)
        for n in (20,50):
            hi=g.High.rolling(n).max().shift();lo=g.Low.rolling(n).min().shift()
            x[f'distance_high_{n}']=c/hi-1
            x[f'range_position_{n}']=(c-lo)/(hi-lo).replace(0,np.nan)
        x['breakout20']=x['distance_high_20'].gt(0).where(x['distance_high_20'].notna()).astype(float)
        for n in (5,10):x[f'positive_days_{n}']=x['return_1'].gt(0).rolling(n).sum()
        up=x['return_1'].gt(0);x['green_streak']=up.groupby((~up).cumsum()).cumsum().astype(float)
        parts.append(pd.concat([g,pd.DataFrame(x,index=g.index)],axis=1));names=list(x)
    f=pd.concat(parts,ignore_index=True)
    spy=f[f.Ticker.eq('SPY')].set_index('Date');stocks=~f.Ticker.eq('SPY')
    for n in (5,10,20):
        col=f'return_{n}';m=f[stocks].groupby('Date')[col].median()
        f[f'rs_spy_{n}']=f[col]-f.Date.map(spy[col])
        f[f'rs_universe_{n}']=f[col]-f.Date.map(m)
        f[f'rank_{n}']=f[stocks].groupby('Date')[col].rank(pct=True)
        names.extend([f'rs_spy_{n}',f'rs_universe_{n}',f'rank_{n}'])
    for col in ('return_1','return_5','distance_sma50','realized_vol_20'):
        f['spy_'+col]=f.Date.map(spy[col]);names.append('spy_'+col)
    return f.replace([np.inf,-np.inf],np.nan),names


def intraday_features(bars,daily):
    parts=[];names=[]
    for (_,session),g in bars.groupby(['Ticker','Session'],sort=True):
        g=g.sort_values('Date').copy();c=g.Close;x={};step=int(g.Minutes.iloc[0])
        for minutes in (5,10,15,30,60):
            if minutes%step==0:x[f'return_{minutes}m']=c.pct_change(minutes//step,fill_method=None)
        x['return_open']=c/g.Open.iloc[0]-1
        x['acceleration']=c.pct_change(fill_method=None)-c.pct_change(fill_method=None).shift()
        vwap=g.DollarVolume.cumsum()/g.Volume.cumsum().replace(0,np.nan)
        x['distance_vwap']=c/vwap-1;x['slope_vwap']=vwap.pct_change(3,fill_method=None)
        above=c.gt(vwap);x['vwap_reclaim']=(above & ~above.shift(fill_value=False)).astype(float)
        x['vwap_hold3']=above.rolling(3).min()
        elapsed=(g.Bar_End-g.Session_Open).dt.total_seconds()/60
        for n in (5,15,30,60):
            if n<step:continue
            # OR becomes known only when its entire interval has closed.
            orhigh=g.High.where(elapsed.le(n)).cummax().ffill().where(elapsed.ge(n))
            x[f'or{n}_distance']=c/orhigh-1
        hod=g.High.cummax();lod=g.Low.cummin()
        x['distance_hod']=c/hod-1;x['new_high']=g.High.gt(hod.shift()).astype(float)
        x['session_range']=(hod-lod)/g.Open.iloc[0]
        x['range_position']=(c-lod)/(hod-lod).replace(0,np.nan)
        x['volume_acceleration']=g.Volume/g.Volume.shift().replace(0,np.nan)-1
        x['volume_breakout']=g.Volume/g.Volume.shift().rolling(3).mean().replace(0,np.nan)
        for n in (9,20,50):
            ema=c.ewm(span=n,adjust=False,min_periods=n).mean()
            x[f'distance_ema{n}']=c/ema-1
        x['align_ema9_20']=c.ewm(span=9,adjust=False,min_periods=9).mean()/c.ewm(span=20,adjust=False,min_periods=20).mean()-1
        x['ema_slope']=c.ewm(span=9,adjust=False,min_periods=9).mean().pct_change(3,fill_method=None)
        spread=(g.High-g.Low).replace(0,np.nan)
        x['clv']=(c-g.Low)/spread;x['body_range']=(c-g.Open)/spread
        up=c.gt(g.Open);x['green_streak']=up.groupby((~up).cumsum()).cumsum().astype(float)
        x['range_expansion']=spread/spread.shift().rolling(6).mean()
        parts.append(pd.concat([g,pd.DataFrame(x,index=g.index)],axis=1));names=list(x)
    f=pd.concat(parts,ignore_index=True).sort_values(['Ticker','Date']).reset_index(drop=True)
    slot=(f.Date-f.Session_Open).dt.total_seconds()/60
    f['Slot']=slot
    # Previous sessions at this time only, never the rest of the current day.
    historic=f.groupby(['Ticker','Slot']).Volume.transform(lambda s:s.shift().rolling(20,min_periods=3).mean())
    f['relative_volume']=f.Volume/historic.replace(0,np.nan);names.append('relative_volume')
    spy=f[f.Ticker.eq('SPY')].set_index('Date');stocks=~f.Ticker.eq('SPY')
    for n in (5,15,30,60):
        col=f'return_{n}m'
        if col not in f:continue
        med=f[stocks].groupby('Date')[col].median()
        f[f'rs_spy_{n}m']=f[col]-f.Date.map(spy[col]);f[f'rs_universe_{n}m']=f[col]-f.Date.map(med)
        f[f'rank_{n}m']=f[stocks].groupby('Date')[col].rank(pct=True)
        names.extend([f'rs_spy_{n}m',f'rs_universe_{n}m',f'rank_{n}m'])
    # Strict previous daily date, including on weekends/holidays; same-day close forbidden.
    ctx=['return_5','return_10','return_20','distance_sma20','distance_sma50','atr_pct_14','rs_spy_20']
    d,_=daily_features(daily)
    result=[]
    for ticker,g in f.groupby('Ticker',sort=True):
        day=d[d.Ticker.eq(ticker)][['Date']+ctx].sort_values('Date').rename(columns={'Date':'Daily_Date',**{k:'daily_'+k for k in ctx}})
        g=g.copy();g['Join_Date']=pd.to_datetime(g.Session)
        g=pd.merge_asof(g.sort_values('Join_Date'),day,left_on='Join_Date',right_on='Daily_Date',direction='backward',allow_exact_matches=False)
        if (g.Daily_Date>=g.Join_Date).any():raise AssertionError('Same-day daily context')
        result.append(g)
    names.extend('daily_'+k for k in ctx)
    return pd.concat(result,ignore_index=True).sort_values(['Ticker','Date']).reset_index(drop=True).replace([np.inf,-np.inf],np.nan),names
