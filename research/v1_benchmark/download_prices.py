"""Download the frozen universe, never rebuild it. No trading calculations."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ROOT / 'data/universe/top100_us_v1.csv'
CACHE = ROOT / 'data/cache/v1_top100'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(UNIVERSE)
    overrides = json.loads((Path(__file__).parent/'data_overrides.json').read_text())
    assert len(universe) == universe.ticker.nunique() == 100
    frames, audit = [], []
    for ticker in list(universe.ticker) + ['SPY']:
        # SPCX listed in 2026. Keep in universe, never fabricate earlier data.
        if ticker == 'SPCX':
            audit.append(dict(ticker=ticker, status='IPO_AFTER_PERIOD', rows=0,
                              source='https://www.sec.gov/Archives/edgar/data/1181412/000162828026042466/spaceexplorationtechnologi.htm'))
            continue
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(ticker) + '?' + urlencode({
            'period1': 1388534400, 'period2': 1767225600, 'interval': '1d',
            'events': 'div,splits', 'includeAdjustedClose': 'true'})
        raw = args.cache / f'{ticker}.json'
        if not raw.exists():
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=60) as response:
                payload = response.read()
            json.loads(payload)  # Never cache an HTML error as a valid response.
            raw.write_bytes(payload)
            time.sleep(.25)
        result = json.loads(raw.read_bytes())['chart']['result'][0]
        if result['meta']['currency'] != 'USD':
            raise ValueError(f'{ticker}: not USD')
        q = result['indicators']['quote'][0]
        f = pd.DataFrame({k.title(): v for k, v in q.items()})
        f['Date'] = pd.to_datetime(result['timestamp'], unit='s', utc=True).tz_convert(
            'America/New_York').tz_localize(None).normalize()
        f['Ticker'] = ticker
        # Match yfinance auto_adjust=True: same positive daily factor for OHLC.
        factor = pd.Series(result['indicators']['adjclose'][0]['adjclose']) / f.Close
        for col in ['Open', 'High', 'Low', 'Close']:
            f[col] *= factor
        f = f[['Date', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume']]
        raw_rows = len(f)
        if ticker in overrides:
            f = f[f.Date.ge(overrides[ticker]['start'])].copy()
        if f.isna().any().any() or (f[['Open','High','Low','Close']] <= 0).any().any():
            raise ValueError(f'{ticker}: missing/nonpositive prices; requires data review')
        frames.append(f)
        audit.append(dict(ticker=ticker, status='OK', rows=len(f), start=str(f.Date.min().date()),
                          end=str(f.Date.max().date()), source=url, raw_sha256=sha(raw),
                          excluded_prefix_rows=raw_rows-len(f), override=overrides.get(ticker)))
        print(ticker, len(f), flush=True)
    output = args.cache / 'ohlcv.csv'
    pd.concat(frames).sort_values(['Ticker','Date']).to_csv(output, index=False)
    manifest = dict(retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                    universe_sha256=sha(UNIVERSE), prices_sha256=sha(output),
                    adjustment='OHLC * AdjClose/Close; Volume as delivered', tickers=audit)
    (args.cache / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Saved', output, 'sha256', sha(output))


if __name__ == '__main__':
    main()
