"""Read-only providers. Timestamp contract: UTC start of each one-minute bar."""
import json
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, quote
from urllib.request import Request,urlopen
import numpy as np
import pandas as pd
import exchange_calendars as xc


class IntradayDataProvider(Protocol):
    def get_bars(self,ticker,start,end,timeframe=1)->pd.DataFrame: ...


def _fetch(url,headers=None):
    with urlopen(Request(url,headers=headers or {'User-Agent':'Mozilla/5.0'}),timeout=60) as r:
        return json.loads(r.read())


class CSVProvider:
    """One file per symbol. Explicit UTC timestamps; no silent timezone inference."""
    def __init__(self,directory):self.directory=Path(directory)
    def get_bars(self,ticker,start,end,timeframe=1):
        if timeframe!=1:raise ValueError('Supply raw 1m; aggregate centrally')
        f=pd.read_csv(self.directory/f'{ticker}.csv')
        if not f.Date.astype(str).str.contains(r'Z|[+-]\d\d:\d\d$',regex=True).all():
            raise ValueError('CSV requires explicit timezone offsets')
        f.Date=pd.to_datetime(f.Date,utc=True);f['Ticker']=ticker
        return f[f.Date.ge(pd.Timestamp(start,tz='UTC')) & f.Date.lt(pd.Timestamp(end,tz='UTC'))]


class YahooSampleProvider:
    """Recent sample only; cannot supply multi-year minute history."""
    def __init__(self,cache):self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True)
    def get_bars(self,ticker,start,end,timeframe=1):
        if timeframe!=1:raise ValueError('Raw sample must be 1m')
        p=self.cache/f'{ticker}_{start}_{end}_1m.json'
        if not p.exists():
            args=dict(period1=int(pd.Timestamp(start,tz='UTC').timestamp()),period2=int(pd.Timestamp(end,tz='UTC').timestamp()),interval='1m',includePrePost='false')
            p.write_text(json.dumps(_fetch('https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker)+'?'+urlencode(args))))
        r=json.loads(p.read_text())['chart']['result'][0]
        f=pd.DataFrame({k.title():v for k,v in r['indicators']['quote'][0].items()})
        f['Date']=pd.to_datetime(r['timestamp'],unit='s',utc=True);f['Ticker']=ticker
        return f
    def daily(self,ticker,start,end):
        p=self.cache/f'{ticker}_{start}_{end}_daily.json'
        if not p.exists():
            args=dict(period1=int(pd.Timestamp(start,tz='UTC').timestamp()),period2=int(pd.Timestamp(end,tz='UTC').timestamp()),interval='1d')
            p.write_text(json.dumps(_fetch('https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker)+'?'+urlencode(args))))
        r=json.loads(p.read_text())['chart']['result'][0]
        f=pd.DataFrame({k.title():v for k,v in r['indicators']['quote'][0].items()})
        f['Date']=pd.to_datetime(r['timestamp'],unit='s',utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
        f['Ticker']=ticker
        factor=pd.Series(r['indicators']['adjclose'][0]['adjclose'])/f.Close
        f[['Open','High','Low','Close']]=f[['Open','High','Low','Close']].mul(factor,axis=0)
        return f


class AlpacaProvider:
    """Historical SIP only, configurable feed; never calls trading/order endpoints."""
    def __init__(self,cache,feed='sip'):
        if feed not in ('sip','iex'):raise ValueError('Unsupported feed')
        self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True);self.feed=feed
    def get_bars(self,ticker,start,end,timeframe=1):
        if timeframe!=1:raise ValueError('Request raw 1m')
        key=os.environ.get('APCA_API_KEY_ID');secret=os.environ.get('APCA_API_SECRET_KEY')
        if not key or not secret:raise RuntimeError('Set Alpaca data credentials; no key is configured')
        p=self.cache/f'alpaca_{self.feed}_{ticker}_{start}_{end}.json'
        if p.exists():bars=json.loads(p.read_text())
        else:
            bars=[];token=None
            while True:
                args=dict(symbols=ticker,timeframe='1Min',start=start,end=end,feed=self.feed,adjustment='split',limit=10000,sort='asc',asof='2026-10-02')
                if token:args['page_token']=token
                page=_fetch('https://data.alpaca.markets/v2/stocks/bars?'+urlencode(args),{'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
                bars.extend(page.get('bars',{}).get(ticker,[]));token=page.get('next_page_token')
                if not token:break
            p.write_text(json.dumps(bars))
        if not bars:raise ValueError(f'No data for {ticker}; do not assume delisted')
        f=pd.DataFrame(bars).rename(columns={'t':'Date','o':'Open','h':'High','l':'Low','c':'Close','v':'Volume','vw':'VWAP'})
        f.Date=pd.to_datetime(f.Date,utc=True);f['Ticker']=ticker
        return f[f.Date.lt(pd.Timestamp(end,tz='UTC'))]


def aggregate_minutes(raw,minutes=5):
    if minutes not in (5,15,30):raise ValueError('Supported bars: 5/15/30m')
    f=raw.copy();f.Date=pd.to_datetime(f.Date,utc=True)
    if f.duplicated(['Ticker','Date']).any():raise ValueError('Duplicate minute')
    calendar=xc.get_calendar('XNYS',start=str(f.Date.min().date()),end=str((f.Date.max()+pd.Timedelta(days=1)).date()))
    schedule=calendar.schedule
    parts=[]
    for ticker,g in f.groupby('Ticker'):
        for session,day in g.groupby(g.Date.dt.tz_convert('America/New_York').dt.date):
            key=pd.Timestamp(session)
            if key not in schedule.index:continue
            opened,closed=schedule.loc[key,['open','close']]
            day=day[day.Date.ge(opened)&day.Date.lt(closed)].sort_values('Date').copy()
            if day.empty:continue
            if not day.Date.dt.second.eq(0).all():raise ValueError('Not minute-aligned')
            valid=day[['Open','High','Low','Close','Volume']].notna().all(axis=1)
            valid &= day[['Open','High','Low','Close']].gt(0).all(axis=1)&day.Volume.ge(0)
            valid &= day.High.ge(day[['Open','Close','Low']].max(axis=1))&day.Low.le(day[['Open','Close','High']].min(axis=1))
            if not valid.all():raise ValueError(f'Invalid OHLCV {ticker} {session}')
            minute=((day.Date-opened).dt.total_seconds()/60).astype(int)
            day['Bucket']=minute//minutes
            proxy=day.VWAP if 'VWAP' in day else (day.High+day.Low+day.Close)/3
            day['DollarVolume']=proxy*day.Volume
            agg=day.groupby('Bucket').agg(Open=('Open','first'),High=('High','max'),Low=('Low','min'),Close=('Close','last'),Volume=('Volume','sum'),DollarVolume=('DollarVolume','sum'),Count=('Date','size'))
            agg=agg[agg.Count.eq(minutes)].copy() # Partial intervals are never tradable bars.
            agg['Date']=opened+pd.to_timedelta(agg.index*minutes,unit='min')
            agg['Bar_End']=agg.Date+pd.Timedelta(minutes=minutes)
            agg['Session']=str(session);agg['Session_Open']=opened;agg['Session_Close']=closed
            agg['Ticker']=ticker;agg['Minutes']=minutes
            parts.append(agg.reset_index(drop=True))
    if not parts:raise ValueError('No complete regular-session bars')
    return pd.concat(parts,ignore_index=True).sort_values(['Ticker','Date']).reset_index(drop=True)


def require_complete_sessions(bars):
    """Fail instead of using next available bar as if it were the next scheduled bar."""
    for ticker,g in bars.groupby('Ticker'):
        first=pd.Timestamp(g.Session.min());last=pd.Timestamp(g.Session.max())
        cal=xc.get_calendar('XNYS',start=first,end=last+pd.Timedelta(days=1))
        expected=cal.sessions_in_range(first,last).strftime('%Y-%m-%d')
        if set(expected)!=set(g.Session):raise ValueError(f'Entire session missing for {ticker}')
    for (ticker,session),g in bars.groupby(['Ticker','Session']):
        step=int(g.Minutes.iloc[0]);expected=pd.date_range(g.Session_Open.iloc[0],g.Session_Close.iloc[0],freq=f'{step}min',inclusive='left')
        if not expected.equals(pd.DatetimeIndex(g.sort_values('Date').Date)):
            raise ValueError(f'Incomplete session {ticker} {session}; resolve before research')
