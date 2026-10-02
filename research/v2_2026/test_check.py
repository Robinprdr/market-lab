import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from research.research_v2.providers import AlpacaProvider
from research.v2_2026.audit_alpaca import diagnose
from research.v2_2026.run import ROOT, locked_inputs, prepare_lab, selected_trades, stats, verdict, portfolio


class FrozenCheckTests(unittest.TestCase):
    def test_frozen_candidate_and_cost(self):
        cfg, candidate, cost = locked_inputs()
        self.assertEqual(candidate['id'], cfg['candidate_id'])
        self.assertEqual(candidate['horizon'], 9)
        self.assertEqual(cost, .002)
        self.assertEqual(candidate['rules'], [
            {'feature':'align_sma20_50','op':'>','threshold':0.0},
            {'feature':'return_40','op':'>=','threshold':0.11960506972844002},
            {'feature':'align_ema9_20','op':'>=','threshold':0.01738968742745084},
            {'feature':'distance_high_20','op':'<=','threshold':-0.09276280088410362}])
        before = json.dumps(candidate,sort_keys=True)
        _ = copy.deepcopy(candidate)
        self.assertEqual(json.dumps(candidate,sort_keys=True),before)

    def test_2026_only_and_prior_history_for_indicators(self):
        dates = pd.bdate_range('2025-01-01','2026-01-16')
        rows=[]
        for ticker in ('AAA','SPY'):
            for i,date in enumerate(dates):
                price=100+i*.1
                rows.append(dict(Date=date,Ticker=ticker,Open=price,High=price+1,Low=price-1,Close=price+.2,Volume=1000))
        raw=pd.DataFrame(rows)
        cfg={'start':'2026-01-01','last_complete_session':'2026-01-16'}
        lab=prepare_lab(raw,cfg,1,.002)
        self.assertTrue(lab.f.Date.ge('2026-01-01').all())
        self.assertTrue(lab.f.return_40.notna().all())
        # Prior rows are needed for the first evaluable 2026 feature, never for trade dates.
        self.assertTrue(np.isfinite(lab.f.iloc[0].return_40))
        trades,_=selected_trades(lab,{'horizon':1,'rules':[{'feature':'return_40','op':'>','threshold':0.0}]})
        self.assertTrue(trades.Signal.ge('2026-01-01').all())
        self.assertTrue(trades.Entry.gt(trades.Signal).all())
        self.assertTrue(trades.Exit.le('2026-01-16').all())
        self.assertTrue(np.allclose(trades.Net,trades.Gross-.002))

    def test_costs_and_verdict_are_fixed(self):
        t=pd.DataFrame({'Gross':[.05,-.01], 'Net':[.048,-.012]})
        s=stats(t)
        self.assertAlmostEqual(s['average_net'],.018)
        self.assertAlmostEqual(s['pf_net'],4.)
        self.assertEqual(verdict(s,.01,s),'WEAK')
        self.assertEqual(verdict({**s,'trades':30},.01,s),'PASS')
        self.assertEqual(verdict({**s,'trades':30,'average_net':-.001},-.01,s),'FAIL')

    def test_portfolio_cost_and_timing(self):
        dates=pd.bdate_range('2026-01-01','2026-01-06')
        raw=pd.DataFrame([dict(Date=d,Ticker='AAA',Open=100.,High=111.,Low=99.,Close=110.,Volume=1000) for d in dates])
        signals=pd.DataFrame([dict(Ticker='AAA',Signal=dates[0],Entry=dates[1],Exit=dates[2],Gross=.1,Net=.098)])
        cfg={'start':'2026-01-01','last_complete_session':'2026-01-06',
             'portfolio':{'initial_usd':10000,'weight_per_entry':.1,'max_positions':5}}
        accepted,curve,total,dd=portfolio(raw,signals,pd.DatetimeIndex(dates),cfg,.002)
        self.assertEqual(len(accepted),1)
        self.assertAlmostEqual(accepted.Net.iloc[0],.098)
        self.assertAlmostEqual(accepted.Net_USD.iloc[0],98.)
        self.assertAlmostEqual(total,.0098)
        self.assertEqual(accepted.Entry.iloc[0],dates[1])

    def test_no_git_tracked_credentials(self):
        files=subprocess.check_output(['git','ls-files','--cached'],cwd=ROOT,text=True).splitlines()
        self.assertFalse(any(Path(x).name in ('.env','.env.local') or x.endswith(('.pem','.key')) for x in files))
        for name in ('APCA_API_KEY_ID','APCA_API_SECRET_KEY'):
            value=os.environ.get(name)
            if value and len(value)>8:
                self.assertFalse(any(value in (ROOT/f).read_text(errors='ignore') for f in files if (ROOT/f).is_file()))


class AlpacaAuditTests(unittest.TestCase):
    def test_pagination_and_timestamp(self):
        bar1={'t':'2026-09-28T13:30:00Z','o':100.,'h':101.,'l':99.,'c':100.5,'v':500}
        bar2={'t':'2026-09-28T13:31:00Z','o':100.5,'h':101.,'l':100.,'c':100.75,'v':400}
        pages=[{'bars':{'AAPL':[bar1]},'next_page_token':'next'},
               {'bars':{'AAPL':[bar2]},'next_page_token':None}]
        urls=[]
        def fake_fetch(url,headers):
            urls.append(url)
            self.assertEqual(headers['APCA-API-KEY-ID'],'test-key')
            return pages[len(urls)-1]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'APCA_API_KEY_ID':'test-key','APCA_API_SECRET_KEY':'test-secret'}), patch('research.research_v2.providers._fetch',side_effect=fake_fetch):
            data=AlpacaProvider(tmp,'iex').get_bars('AAPL','2026-09-28','2026-09-29')
            self.assertEqual(len(urls),2)
            self.assertIn('page_token=next',urls[1])
            self.assertEqual(len(data),2)
            report=diagnose(data,'AAPL','iex','recent_2026')
            self.assertEqual(str(data.Date.dt.tz),'UTC')
            self.assertIn('09:30:00-04:00',report['first_new_york'])
            self.assertEqual(report['sessions'][0]['observed_regular_minutes'],2)
            self.assertEqual(report['sessions'][0]['missing_minutes'],388)


if __name__ == '__main__':
    unittest.main()
