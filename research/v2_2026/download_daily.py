"""Fetch adjustment-consistent daily OHLCV from Yahoo for warmup and 2026.

Raw responses and the combined panel stay in ignored data/cache. The frozen
Top100 snapshot is reused; no ranking or rule changes are made here.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'data/cache/v2_2026_check'
PROTOCOL = Path(__file__).with_name('protocol.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch(ticker, start, end, cache):
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(ticker) + '?' + urlencode({
        'period1': int(pd.Timestamp(start, tz='UTC').timestamp()),
        'period2': int((pd.Timestamp(end, tz='UTC') + pd.Timedelta(days=1)).timestamp()),
        'interval': '1d', 'events': 'div,splits', 'includeAdjustedClose': 'true'})
    path = cache / (ticker + '.json')
    if not path.exists():
        for attempt in range(5):
            try:
                with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60) as response:
                    payload = response.read()
                obj = json.loads(payload)
                if not obj.get('chart', {}).get('result'):
                    raise ValueError(f'{ticker}: invalid Yahoo response')
                path.write_bytes(payload)
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        time.sleep(.2)
    result = json.loads(path.read_bytes())['chart']['result'][0]
    if result['meta'].get('currency') != 'USD':
        raise ValueError(f'{ticker}: currency not USD')
    q = result['indicators']['quote'][0]
    frame = pd.DataFrame({k.title(): v for k, v in q.items()})
    frame['Date'] = pd.to_datetime(result['timestamp'], unit='s', utc=True).tz_convert('America/New_York').tz_localize(None).normalize()
    frame['Ticker'] = ticker
    factor = pd.Series(result['indicators']['adjclose'][0]['adjclose']) / frame.Close
    frame[['Open', 'High', 'Low', 'Close']] = frame[['Open', 'High', 'Low', 'Close']].mul(factor, axis=0)
    frame = frame[['Date', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume']]
    frame = frame[frame.Date.between(start, end)].copy()
    if frame[['Open','High','Low','Close','Volume']].isna().any().any():
        raise ValueError(f'{ticker}: null OHLCV')
    if (frame[['Open','High','Low','Close']] <= 0).any().any():
        raise ValueError(f'{ticker}: non-positive price')
    if frame.duplicated('Date').any():
        raise ValueError(f'{ticker}: duplicate date')
    return frame, {'ticker': ticker, 'raw_sha256': sha(path), 'url': url,
                   'first': str(frame.Date.min().date()), 'last': str(frame.Date.max().date()), 'rows': len(frame)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, default=CACHE)
    args = parser.parse_args()
    cfg = json.loads(PROTOCOL.read_text())
    args.cache.mkdir(parents=True, exist_ok=True)
    tickers = list(pd.read_csv(ROOT/'data/universe/top100_us_v1.csv').ticker) + ['SPY']
    frames, audit = [], []
    for ticker in tickers:
        frame, note = fetch(ticker, cfg['daily_warmup_start'], cfg['last_complete_session'], args.cache)
        frames.append(frame); audit.append(note)
        print(ticker, len(frame), flush=True)
    panel = pd.concat(frames, ignore_index=True).sort_values(['Ticker','Date'])
    panel.to_csv(args.cache/'ohlcv.csv', index=False)
    (args.cache/'manifest.json').write_text(json.dumps({'source': 'Yahoo chart', 'universe_sha256': sha(ROOT/'data/universe/top100_us_v1.csv'),
        'panel_sha256': sha(args.cache/'ohlcv.csv'), 'last_complete_session': cfg['last_complete_session'],
        'tickers': audit}, indent=2)+'\n')
    print('Saved', len(panel), 'rows', sha(args.cache/'ohlcv.csv'))


if __name__ == '__main__':
    main()
