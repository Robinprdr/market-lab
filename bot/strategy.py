"""Strategy boundary; frozen V2 rules are loaded, never copied or optimized."""
from abc import ABC, abstractmethod
from pathlib import Path
import pandas as pd

from research.research_v2.features import daily_features
from research.research_v2.run import load_frozen
from research.research_v2.search import rule_mask
from .calendar import next_session, exit_session
from .models import Signal

ROOT = Path(__file__).resolve().parents[1]


class Strategy(ABC):
    @property
    @abstractmethod
    def strategy_id(self): ...

    @abstractmethod
    def required_data(self): ...

    @abstractmethod
    def generate_signals(self,ohlcv,asof): ...


class FrozenSwingV2(Strategy):
    def __init__(self):
        frozen = load_frozen(ROOT/'results/research_v2/frozen_candidates.json')
        candidates = [c for c in frozen['candidates'] if c['id']=='2366a81673c5' and c['lab']=='swing']
        if len(candidates)!=1:
            raise ValueError('Frozen swing V2 candidate missing or ambiguous')
        self.candidate = candidates[0]
        if self.candidate['horizon'] != 9:
            raise ValueError('Unexpected frozen holding horizon')

    @property
    def strategy_id(self):
        return self.candidate['id']

    def required_data(self):
        return {'frequency':'1D','warmup_sessions':100,'universe':'top100_us_v1','benchmark':'SPY'}

    def generate_signals(self,ohlcv,asof):
        asof = pd.Timestamp(asof).normalize()
        if ohlcv.Date.max() != asof or ohlcv.Date.gt(asof).any():
            raise ValueError('Future/incomplete daily data in signal input')
        features,_ = daily_features(ohlcv)
        today = features[features.Date.eq(asof)&~features.Ticker.eq('SPY')].copy()
        mask = rule_mask(today,self.candidate['rules'])
        entry = next_session(asof)
        exit_day = exit_session(entry,self.candidate['horizon'])
        reason = 'frozen V2 swing conditions from frozen_candidates.json'
        return [Signal(self.strategy_id,r.Ticker,asof.date().isoformat(),entry,exit_day,
                       float(r.Close),reason,self.candidate['horizon']) for r in today.loc[mask].itertuples(index=False)]
