"""Causality, calendar alignment and cash-ledger tests, without network access."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from research.v1_benchmark import run_benchmark as b


def prices(dates, tickers=('AAA',), closes=None):
    rows = []
    for ticker in tickers:
        for i,date in enumerate(dates):
            close = closes[i] if closes is not None else 100.
            rows.append(dict(Date=date,Ticker=ticker,Open=100.,High=max(100.,close)+1,
                             Low=min(100.,close)-1,Close=close,Volume=1000.))
    return pd.DataFrame(rows)


class BenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range('2018-01-02', periods=7)

    def test_signal_next_open_and_horizons(self):
        f = prices(self.dates)
        f['Momentum'] = False
        f.loc[0,'Momentum'] = True
        for h in (1,2,3):
            e = b.candidates(f,'Momentum',h,self.dates)
            self.assertEqual(e.Entry.iloc[0], self.dates[1])
            self.assertEqual(e.Exit.iloc[0], self.dates[h])

    def test_last_session_purge(self):
        f = prices(self.dates)
        f['Momentum'] = True
        self.assertEqual(len(b.candidates(f,'Momentum',3,self.dates)),4)

    def test_manual_long_accounting(self):
        f = prices(self.dates, closes=[100,110,100,100,100,100,100])
        e = pd.DataFrame([dict(Ticker='AAA',Date=self.dates[0],Entry=self.dates[1],Exit=self.dates[1])])
        t,c = b.portfolio(f,e,self.dates)
        self.assertAlmostEqual(t.Gross.iloc[0], .10)
        self.assertAlmostEqual(t.Net.iloc[0], .098)
        self.assertAlmostEqual(t.Notional.iloc[0], 1000.)
        self.assertAlmostEqual(c.Net_Equity.iloc[-1], 10098.)
        self.assertAlmostEqual(c.Gross_Equity.iloc[-1], 10100.)

    def test_positions_overlap_and_no_open_reuse_of_close(self):
        f = prices(self.dates)
        e = pd.DataFrame([dict(Ticker='AAA',Date=self.dates[0],Entry=self.dates[i],Exit=self.dates[i+2])
                          for i in (1,2,3,4)])
        t,c = b.portfolio(f,e,self.dates)
        self.assertEqual(t.Entry.tolist(), [self.dates[1],self.dates[4]])

    def test_capacity_and_deterministic_order(self):
        tickers = ['FFF','EEE','DDD','CCC','BBB','AAA']
        f = prices(self.dates,tickers)
        e = pd.DataFrame([dict(Ticker=t,Date=self.dates[0],Entry=self.dates[1],Exit=self.dates[2]) for t in tickers])
        t,c = b.portfolio(f,e,self.dates)
        self.assertEqual(t.Ticker.tolist(),sorted(tickers)[:5])
        self.assertEqual(c.Open_Positions.max(),5)
        self.assertAlmostEqual(c.Net_Equity.iloc[-1],9990.)

    def test_mtm_drawdown_includes_initial_capital(self):
        f = prices(self.dates,closes=[100,50,100,100,100,100,100])
        e = pd.DataFrame([dict(Ticker='AAA',Date=self.dates[0],Entry=self.dates[1],Exit=self.dates[2])])
        t,c = b.portfolio(f,e,self.dates)
        m = b.portfolio_metrics(c)
        self.assertAlmostEqual(m['Net_Max_Drawdown'], -.0501)
        self.assertAlmostEqual(m['Net_Total_Return'], -.0002)

    def test_remove_ticker_frees_slot_without_changing_signal(self):
        tickers = ['AAA','BBB','CCC','DDD','EEE','FFF']
        f = prices(self.dates,tickers)
        e = pd.DataFrame([dict(Ticker=t,Date=self.dates[0],Entry=self.dates[1],Exit=self.dates[1]) for t in tickers])
        t,_ = b.portfolio(f,e,self.dates,excluded=['AAA'])
        self.assertEqual(t.Ticker.tolist(),tickers[1:])

    def test_episode_reset_multiple_tickers(self):
        # Supply indicator inputs to isolate the existing A episode definition.
        f = prices(pd.to_datetime(['2017-01-03','2017-01-04','2017-01-05','2017-01-06']),('AAA','BBB','SPY'))
        f['SMA50'],f['SMA20'],f['R20'] = 80.,90.,.10
        f['R3'] = [1.,-.01,-.01,.01] + [-.01,-.01,.01,-.01] + [0.]*4
        f['R1'],f['R10'],f['ATR_Pct'] = 0.,0.,.02
        f['Distance20'],f['Distance50'],f['Volume20'] = 0.,0.,1000.
        with patch.object(b,'indicators',return_value=f):
            out,_ = b.signals(f)
        self.assertEqual(out[out.Ticker.eq('AAA')].Pullback.tolist(),[False,True,False,False])
        self.assertEqual(out[out.Ticker.eq('BBB')].Pullback.tolist(),[True,False,False,True])

    def test_future_prices_cannot_change_past_signals(self):
        dates = pd.bdate_range('2014-01-02','2025-12-31')
        f = prices(dates,('AAA','SPY'))
        f['Close'] = 100 + np.sin(np.arange(len(f))/10)*5 + np.arange(len(f))*.005
        f['High'],f['Low'],f['Open'] = f.Close+1,f.Close-1,f.Close
        out,threshold = b.signals(f)
        altered = f.copy()
        future = altered.Date.ge('2024-07-01')
        altered.loc[future,['Open','High','Low','Close']] *= 4
        other,threshold2 = b.signals(altered)
        past = out.Date.lt('2024-07-01')
        pd.testing.assert_frame_equal(out.loc[past,list(b.STRATEGIES)],other.loc[past,list(b.STRATEGIES)])
        self.assertEqual(threshold[2024],threshold2[2024])

    def test_mean_reversion_existing_score5_filter(self):
        f = prices(pd.to_datetime(['2017-01-03']),('AAA','BBB','SPY'))
        f['SMA50'],f['SMA20'] = 90.,95.
        f['R1'],f['R3'],f['R10'],f['R20'] = -.03,-.01,.05,.05
        f['ATR_Pct'],f['Volume20'] = .02,900.
        f['Distance20'],f['Distance50'] = .05,.10
        f.loc[f.Ticker.eq('BBB'),'Distance50'] = .049
        f.loc[f.Ticker.eq('SPY'),'R1'] = -.019
        with patch.object(b,'indicators',return_value=f):
            out,_ = b.signals(f)
        self.assertEqual(out.MeanReversion.tolist(),[True,False])

    def test_annual_equity_reconciles(self):
        dates = pd.to_datetime([f'{y}-12-31' for y in range(2018,2026)])
        curve = pd.DataFrame(dict(Date=dates,Net_Equity=np.arange(10100,10900,100),Gross_Equity=np.arange(10200,11800,200)))
        t = pd.DataFrame({'Entry':pd.to_datetime([]),'Gross':[],'Net':[],'Gross_USD':[],'Net_USD':[]})
        rows = b.annual_rows(t,curve)
        self.assertAlmostEqual(np.prod([1+r['Net_Portfolio_Return'] for r in rows])-1,.08)


if __name__ == '__main__':
    unittest.main()
