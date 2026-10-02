"""Read-only Alpaca minute audit. Keys are read from environment, never saved."""
import argparse
import json
import os
from pathlib import Path

import exchange_calendars as xc
import pandas as pd

from research.research_v2.providers import AlpacaProvider

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT/'data/cache/v2_2026_check/alpaca'
OUT = ROOT/'results/research_v2_2026/alpaca_audit.json'
TICKERS = ('AAPL','MSFT','NVDA','AMZN','META','SPY')
WINDOWS = {'older_2018': ('2018-06-04','2018-06-07'),
           'recent_2026': ('2026-09-28','2026-10-02')}


def diagnose(frame, ticker, feed, window):
    if frame.empty:
        raise ValueError(f'{ticker} {feed} {window}: empty')
    if frame.Date.dt.tz is None or str(frame.Date.dt.tz) != 'UTC':
        raise ValueError('Alpaca timestamps must be UTC-aware')
    if frame.Date.duplicated().any() or not frame.Date.is_monotonic_increasing:
        raise ValueError('Duplicate or unordered minute timestamps')
    if (frame.Date.dt.second != 0).any() or (frame.Date.dt.microsecond != 0).any():
        raise ValueError('Non-minute-aligned timestamp')
    cols = ['Open','High','Low','Close','Volume']
    if frame[cols].isna().any().any() or (frame[cols[:4]] <= 0).any().any() or (frame.Volume < 0).any():
        raise ValueError('Invalid OHLCV')
    if (frame.High < frame[['Open','Low','Close']].max(axis=1)).any() or (frame.Low > frame[['Open','High','Close']].min(axis=1)).any():
        raise ValueError('Invalid high/low range')
    ny = frame.Date.dt.tz_convert('America/New_York')
    final = pd.Timestamp(WINDOWS[window][1])-pd.Timedelta(days=1)
    cal = xc.get_calendar('XNYS', start=WINDOWS[window][0], end=final)
    sessions = []
    for session in cal.sessions_in_range(pd.Timestamp(WINDOWS[window][0]),final):
        opened, closed = cal.schedule.loc[session,['open','close']]
        g = frame[frame.Date.ge(opened)&frame.Date.lt(closed)]
        expected = pd.date_range(opened,closed,freq='1min',inclusive='left')
        missing = expected.difference(g.Date)
        sessions.append(dict(session=str(session.date()),expected_minutes=len(expected),observed_regular_minutes=len(g),
                             missing_minutes=len(missing),first_missing_utc=str(missing[0]) if len(missing) else None))
    return dict(ticker=ticker,feed=feed,window=window,total_bars=len(frame),first_utc=str(frame.Date.min()),
                last_utc=str(frame.Date.max()),first_new_york=str(ny.min()),last_new_york=str(ny.max()),
                columns=[c for c in cols+['VWAP'] if c in frame],sessions=sessions)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--basic-account-confirmed', action='store_true',
                        help='Use only after independently confirming these credentials are on Alpaca Basic/free')
    args = parser.parse_args()
    has_keys = bool(os.environ.get('APCA_API_KEY_ID') and os.environ.get('APCA_API_SECRET_KEY'))
    result = dict(credentials_present=has_keys,request_status='not_tested_no_credentials' if not has_keys else 'attempted',
                  basic_account_confirmed=args.basic_account_confirmed,samples=[],errors=[],documented_free_feed='iex',
                  sip='historical older than 15 minutes may be accessible on Basic; must verify with actual account',
                  verdict='ALPACA_FREE_LIMITED')
    if has_keys:
        for feed in ('iex','sip'):
            provider = AlpacaProvider(CACHE,feed=feed)
            for window,(start,end) in WINDOWS.items():
                for ticker in TICKERS:
                    try:
                        frame = provider.get_bars(ticker,start,end)
                        result['samples'].append(diagnose(frame,ticker,feed,window))
                    except Exception as exc:
                        # Never include response body: providers may echo credentials.
                        result['errors'].append(dict(ticker=ticker,feed=feed,window=window,error_type=type(exc).__name__))
        complete_sip = len([x for x in result['samples'] if x['feed']=='sip']) == len(TICKERS)*len(WINDOWS)
        result['verdict'] = 'ALPACA_FREE_OK' if args.basic_account_confirmed and complete_sip and not result['errors'] and all(
            s['missing_minutes']==0 for x in result['samples'] if x['feed']=='sip' for s in x['sessions']) else 'ALPACA_FREE_LIMITED'
        if not result['samples']:
            result['verdict'] = 'ALPACA_FREE_NOT_SUITABLE'
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'samples'},indent=2))


if __name__ == '__main__':
    main()
