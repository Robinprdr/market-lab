"""Daily provider independent of IBKR, reusing the Yahoo/Top100 data path."""
from pathlib import Path
from typing import Protocol
import json
import pandas as pd

from research.v2_2026.download_daily import fetch,sha
from .calendar import last_complete_session

ROOT = Path(__file__).resolve().parents[1]


class MarketDataProvider(Protocol):
    def load(self,asof: str) -> pd.DataFrame: ...


class YahooDailyProvider:
    def __init__(self,cache=None):
        self.cache = Path(cache or ROOT/'data/cache/bot_core/yahoo')

    def load(self,asof):
        if str(asof) > last_complete_session():
            raise ValueError('Requested session is not yet complete')
        tickers = list(pd.read_csv(ROOT/'data/universe/top100_us_v1.csv').ticker)+['SPY']
        prior = ROOT/'data/cache/v2_2026_check'
        manifest = prior/'manifest.json'
        panel_path = prior/'ohlcv.csv'
        if manifest.exists() and panel_path.exists():
            recorded = json.loads(manifest.read_text())
            if recorded.get('last_complete_session') == str(asof) and recorded.get('panel_sha256') == sha(panel_path):
                panel = pd.read_csv(panel_path,parse_dates=['Date'])
                if set(panel.Ticker)==set(tickers) and panel.Date.max()==pd.Timestamp(asof):
                    return panel
        cache = self.cache/str(asof)
        cache.mkdir(parents=True,exist_ok=True)
        frames=[]
        for ticker in tickers:
            frame,_ = fetch(ticker,'2025-01-01',str(asof),cache)
            if frame.Date.max() != pd.Timestamp(asof):
                raise ValueError(f'{ticker}: final session not available')
            frames.append(frame)
        panel = pd.concat(frames,ignore_index=True).sort_values(['Ticker','Date'])
        calendar = pd.DatetimeIndex(sorted(panel.loc[panel.Ticker.eq('SPY'),'Date'].unique()))
        for ticker,g in panel.groupby('Ticker'):
            expected = calendar[(calendar>=g.Date.min())&(calendar<=pd.Timestamp(asof))]
            if len(expected.difference(g.Date)):
                raise ValueError(f'{ticker}: missing daily sessions')
        return panel

    def unadjusted_bar_price(self,ticker,session,asof,side):
        """Raw auction proxy for comparing IB paper fills, never for signals."""
        candidates=[self.cache/str(asof)/(ticker+'.json'),
                    ROOT/'data/cache/v2_2026_check'/(ticker+'.json')]
        for path in candidates:
            if not path.exists():continue
            result=json.loads(path.read_bytes())['chart']['result'][0]
            dates=pd.to_datetime(result['timestamp'],unit='s',utc=True).tz_convert('America/New_York').date
            for index,date in enumerate(dates):
                if date.isoformat()==session:
                    value=result['indicators']['quote'][0]['open' if side=='BUY' else 'close'][index]
                    return float(value) if value is not None else None
        return None
