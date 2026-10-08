"""Focused causal, execution, quality, and stage-isolation invariants."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from .features import aggregate,intraday,attach_daily,cross_section,CONTEXT
from .evaluate import outcomes,selected,trade_rows
from .download import quality,schedule,fetch
from .common import cost,protocol,write,sha
from .search import verify_frozen,generate_initial


def minutes(day='2025-03-10',ticker='AAPL',length=390):
    import exchange_calendars as xc
    s=xc.get_calendar('XNYS',start=str(pd.Timestamp(day)-pd.Timedelta(days=3)),end=str(pd.Timestamp(day)+pd.Timedelta(days=3))).schedule.loc[pd.Timestamp(day)];opened,closed=s['open'],s['close']
    dates=pd.date_range(opened,periods=min(length,int((closed-opened).total_seconds()/60)),freq='1min')
    close=100+np.arange(len(dates))*.01
    return pd.DataFrame(dict(Date=dates,Open=close-.005,High=close+.02,Low=close-.02,Close=close,Volume=1000.,VWAP=close,Ticker=ticker,Session=day,Session_Open=opened,Session_Close=closed))

class CausalityTests(unittest.TestCase):
    def test_aggregation(self):
        raw=minutes();f=aggregate(raw);self.assertEqual(len(f),78);self.assertEqual(f.Open.iloc[0],raw.Open.iloc[0]);self.assertEqual(f.Close.iloc[0],raw.Close.iloc[4]);self.assertEqual(f.Volume.iloc[0],5000);self.assertTrue(f.Complete.all())
    def test_duplicate(self):
        raw=minutes();self.assertRaises(ValueError,aggregate,pd.concat([raw,raw.iloc[:1]]))
    def test_missing_grid_no_compression(self):
        raw=minutes().drop(index=7);f=aggregate(raw);self.assertEqual(len(f),78);self.assertFalse(f.Complete.iloc[1]);self.assertTrue(pd.isna(f.Open.iloc[1]));self.assertTrue(f.Feature_Eligible.iloc[0]);self.assertFalse(f.Feature_Eligible.iloc[2])
    def test_future_gap_does_not_remove_earlier_signal(self):
        a=aggregate(minutes());b=aggregate(minutes().drop(index=200));self.assertEqual(a.Feature_Eligible.iloc[10],b.Feature_Eligible.iloc[10])
    def test_future_prices_cannot_change_features(self):
        raw=minutes();before=intraday(aggregate(raw));raw.loc[raw.index>=100,['Open','High','Low','Close','VWAP']]*=2;raw.loc[raw.index>=100,'Volume']*=8
        after=intraday(aggregate(raw));pd.testing.assert_frame_equal(before.iloc[:20],after.iloc[:20])
    def test_vwap_exact(self):
        raw=minutes();f=intraday(aggregate(raw));self.assertAlmostEqual(f.VWAP.iloc[1],(raw.VWAP.iloc[:10]*raw.Volume.iloc[:10]).sum()/raw.Volume.iloc[:10].sum())
    def test_or_unavailable_then_frozen(self):
        raw=minutes();f=intraday(aggregate(raw));self.assertTrue(f.or15_distance.iloc[:2].isna().all());high=raw.High.iloc[:15].max();self.assertAlmostEqual(f.or15_distance.iloc[8],f.Close.iloc[8]/high-1)
    def test_relative_volume_prior_sessions_only(self):
        frames=[]
        for d in pd.bdate_range('2025-03-03',periods=12):
            try:frames.append(aggregate(minutes(str(d.date()))))
            except ValueError:pass
        f=pd.concat(frames,ignore_index=True);last=f.Session.iloc[-1];f.loc[f.Session.eq(last),'Volume']*=3
        features=intraday(f);self.assertAlmostEqual(features[features.Session.eq(last)].relative_volume.iloc[0],3.)
    def test_daily_strict_prior_date(self):
        f=intraday(aggregate(minutes('2025-03-10')));ctx=pd.DataFrame({'Session':['2025-03-07','2025-03-10'],**{k:[1.,999.] for k in CONTEXT}});a=attach_daily(f,ctx);self.assertTrue(a.daily_return_5.eq(1).all());self.assertTrue((a.Daily_Date<pd.to_datetime(a.Session)).all())
    def test_dst(self):
        before=aggregate(minutes('2025-03-07'));after=aggregate(minutes('2025-03-10'));self.assertEqual(before.Date.iloc[0].hour,14);self.assertEqual(after.Date.iloc[0].hour,13);self.assertEqual(after.Date.iloc[0].tz_convert('America/New_York').hour,9)
    def test_early_close(self):
        f=aggregate(minutes('2025-11-28'));self.assertEqual(len(f),42);self.assertEqual(f.Bar_End.iloc[-1].tz_convert('America/New_York').hour,13)
    def test_quality_ohcl_and_missing(self):
        raw=minutes();raw.loc[5,'High']=0;good,diag=quality(raw,'AAPL',2025,schedule(2025,'2025-03-11'));self.assertEqual(diag[0]['invalid_bars'],1);self.assertEqual(len(good),389)
    def test_cross_section_current_only(self):
        f=intraday(aggregate(minutes()));spy=intraday(aggregate(minutes(ticker='SPY')));full=pd.concat([f,spy]);a=cross_section(full);future=full.Date>full.Date.iloc[10];full.loc[future,'return_15m']=99; b=cross_section(full);pd.testing.assert_series_equal(a.rank_15m.iloc[:11],b.rank_15m.iloc[:11])

class ExecutionTests(unittest.TestCase):
    def arrays(self):
        f=intraday(aggregate(minutes()));n=len(f);return f,np.zeros(n,np.int32),np.zeros(n,np.int32)
    def test_entry_next_bar_not_current(self):
        f,t,s=self.arrays();r,e=outcomes(f.Open.to_numpy(),f.Close.to_numpy(),f.Complete.to_numpy(),t,s,np.array([3]));self.assertAlmostEqual(r[0,0],f.Close.iloc[3]/f.Open.iloc[1]-1);self.assertEqual(e[0,0],3)
    def test_no_overnight(self):
        f,t,s=self.arrays();r,e=outcomes(f.Open.to_numpy(),f.Close.to_numpy(),f.Complete.to_numpy(),t,s,np.array([24]));self.assertTrue(np.isnan(r[0,-24:]).all())
    def test_forced_eod(self):
        f,t,s=self.arrays();r,e=outcomes(f.Open.to_numpy(),f.Close.to_numpy(),f.Complete.to_numpy(),t,s,np.array([0]));self.assertEqual(e[0,2],77);self.assertAlmostEqual(r[0,2],f.Close.iloc[-1]/f.Open.iloc[3]-1)
    def test_future_missing_invalidates_only_affected_outcomes(self):
        f,t,s=self.arrays();complete=f.Complete.to_numpy();complete[20]=False;r,e=outcomes(f.Open.to_numpy(),f.Close.to_numpy(),complete,t,s,np.array([3]));self.assertTrue(np.isnan(r[0,18]));self.assertTrue(np.isfinite(r[0,10]));self.assertTrue(np.isfinite(r[0,21]))
    def test_no_overlap(self):
        mask=np.ones(8,dtype=bool);r=np.ones(8);e=np.arange(8)+3;e[-3:]=-1;r[-3:]=np.nan;t=np.zeros(8,np.int32);chosen=selected(mask,r,e,t);self.assertEqual(np.flatnonzero(chosen).tolist(),[0,3])
    def test_multiple_tickers(self):
        mask=np.ones(8,dtype=bool);r=np.ones(8);e=np.array([3,3,3,3,7,7,7,7]);t=np.array([0,0,0,0,1,1,1,1]);chosen=selected(mask,r,e,t);self.assertTrue(chosen[0]);self.assertTrue(chosen[4])
    def test_cost_entry_notional(self):
        cfg=protocol();self.assertAlmostEqual(cost(cfg),.0014);self.assertAlmostEqual(.01-cost(cfg),.0086);self.assertAlmostEqual(.01-2*cost(cfg),.0072)
    def test_zero_cost_exact(self):
        cfg={'base_cost':{'commission':0,'spread':0,'slip':0}};gross=110/100-1;self.assertEqual(gross-cost(cfg),gross)
    def test_portfolio_cash_and_mark_to_market(self):
        from . import validate
        f,t,s=self.arrays();cfg=protocol();start=f.Date.iloc[1];end=f.Bar_End.iloc[3];gross=f.Close.iloc[3]/f.Open.iloc[1]-1
        trades=pd.DataFrame([dict(candidate='mock',ticker='AAPL',session=f.Session.iloc[0],signal_time=start,entry_time=start,exit_time=end,entry=f.Open.iloc[1],exit=f.Close.iloc[3],gross=gross,net=gross-cost(cfg),stress_net=gross-2*cost(cfg),holding_minutes=15)])
        prices=f[['Ticker','Bar_End','Close']]
        with tempfile.TemporaryDirectory() as d,patch.object(validate,'CACHE',Path(d)),patch.object(validate,'OUT',Path(d)),patch.object(validate,'paths',return_value=[Path('2025-03.parquet')]),patch.object(validate.pd,'read_parquet',return_value=prices):
            result=validate.portfolio(trades,'final',cfg,'mock');self.assertEqual(result['trades'],1);self.assertAlmostEqual(result['ending_equity'],10000+1000*(gross-cost(cfg)));self.assertLessEqual(result['max_drawdown'],0)
    def test_ineligible_retained_but_no_trade(self):
        f,t,s=self.arrays();f.Feature_Eligible=False;rule={'id':'test','conditions':[['return_open','>=',0]],'horizon_bars':3};self.assertTrue(trade_rows(f,rule,protocol()).empty);self.assertEqual(len(f),78)

class IsolationTests(unittest.TestCase):
    def test_protocol_periods(self):
        cfg=protocol();self.assertEqual(cfg['exploration'],['2018-01-01','2023-12-31']);self.assertEqual(cfg['validation'],['2024-01-01','2025-12-31']);self.assertTrue(cfg['final'][0]>'2025-12-31')
    def test_search_calls_only_exploration(self):
        from . import search
        seen=[]
        with patch.object(search,'paths',side_effect=lambda stage:seen.append(stage) or []):search.evaluate([dict(id='x',family='momentum',pass_number=1,conditions=[['return_5m','>=',0]],horizon_bars=3)],protocol())
        self.assertEqual(seen,['exploration'])
    def test_frozen_mutation_rejected(self):
        from . import search
        with tempfile.TemporaryDirectory() as d,patch.object(search,'OUT',Path(d)):
            p=Path(d);write(p/'protocol.json',{'x':1});write(p/'frozen_intraday_candidates.json',{'protocol_sha256':sha(p/'protocol.json')});(p/'frozen_intraday_candidates.sha256').write_text(sha(p/'frozen_intraday_candidates.json'));verify_frozen();(p/'frozen_intraday_candidates.json').write_text('{}');self.assertRaises(ValueError,verify_frozen)
    def test_fixed_search_reproducible(self):
        a=generate_initial(protocol());b=generate_initial(protocol());self.assertEqual(a,b);self.assertTrue(all(len(r['conditions'])<=4 for r in a))
    def test_pagination(self):
        objects=[{'bars':{'AAPL':[{'t':'2025-03-10T13:30:00Z','o':1,'h':1,'l':1,'c':1,'v':1,'vw':1}]},'next_page_token':'next'},{'bars':{'AAPL':[{'t':'2025-03-10T13:31:00Z','o':1,'h':1,'l':1,'c':1,'v':1,'vw':1}]}}]
        with patch('research.intraday_v1.download.api',side_effect=objects):frame,pages=fetch('AAPL','2025-03-10T13:30:00Z','2025-03-10T14:00:00Z')
        self.assertEqual(pages,2);self.assertEqual(len(frame),2)
    def test_berkshire_provider_mapping_preserves_universe(self):
        obj={'bars':{'BRK.B':[{'t':'2025-03-10T13:30:00Z','o':1,'h':1,'l':1,'c':1,'v':1,'vw':1}]}}
        with patch('research.intraday_v1.download.api',return_value=obj) as request:
            frame,pages=fetch('BRK-B','2025-03-10T13:30:00Z','2025-03-10T14:00:00Z')
            self.assertEqual(request.call_args.args[0]['symbols'],'BRK.B');self.assertEqual(frame.Ticker.iloc[0],'BRK-B')
    def test_final_requires_prior_validation(self):
        from . import validate
        with tempfile.TemporaryDirectory() as d,patch.object(validate,'OUT',Path(d)),patch.object(validate,'verify_frozen',return_value={'candidates':[]}),patch('sys.argv',['validate','final']),patch.object(validate,'collect') as read:
            self.assertRaises(SystemExit,validate.main);read.assert_not_called()
    def test_identity_overrides_prevent_predecessor(self):
        from .common import HERE
        obj=json.loads((HERE/'data_overrides.json').read_text());self.assertEqual(obj['SPCX']['start'],'2026-06-12');self.assertEqual(obj['SNDK']['start'],'2025-02-24')
    def test_error_body_and_keys_not_logged(self):
        import io,os,types
        from contextlib import redirect_stdout,redirect_stderr
        from . import download
        from unittest.mock import Mock
        response=Mock(status_code=400,text='PRIVATE_SECRET_DO_NOT_LOG');session=Mock();session.get.return_value=response;buffer=io.StringIO()
        with patch.dict(os.environ,{'APCA_API_KEY_ID':'PRIVATE_ID','APCA_API_SECRET_KEY':'PRIVATE_SECRET'}),patch.object(download,'local',types.SimpleNamespace(session=session)),redirect_stdout(buffer),redirect_stderr(buffer):
            try:download.api({'symbols':'TEST'})
            except RuntimeError as exc:self.assertNotIn('PRIVATE',str(exc))
        self.assertNotIn('PRIVATE',buffer.getvalue());self.assertEqual(session.get.call_args.args[0],'https://data.alpaca.markets/v2/stocks/bars')
    def test_repeated_page_token(self):
        with patch('research.intraday_v1.download.api',return_value={'bars':{},'next_page_token':'same'}):self.assertRaises(ValueError,fetch,'AAPL','2025-03-10T13:30:00Z','2025-03-10T14:00:00Z')

if __name__=='__main__':unittest.main()
