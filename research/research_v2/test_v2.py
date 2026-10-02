import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from .features import daily_features,intraday_features
from .providers import aggregate_minutes,require_complete_sessions,CSVProvider
from .search import Lab,rule_mask
from .run import freeze_file,load_frozen,HERE,sha


def minute_data(days=('2024-11-27',),end='16:00'):
    rows=[]
    for ticker in ('AAA','SPY'):
        for day in days:
            dates=pd.date_range(day+' 09:30',day+' '+end,freq='1min',tz='America/New_York',inclusive='left')
            for i,date in enumerate(dates):
                p=100+i*.01;rows.append(dict(Date=date.tz_convert('UTC'),Ticker=ticker,Open=p,High=p+.04,Low=p-.03,Close=p+.01,Volume=100+i))
    return pd.DataFrame(rows)


def daily_data():
    rows=[]
    for ticker in ('AAA','SPY'):
        for i,date in enumerate(pd.bdate_range('2023-01-02','2024-12-31')):
            p=100+i*.01+np.sin(i/7);rows.append(dict(Date=date,Ticker=ticker,Open=p,High=p+1,Low=p-1,Close=p+.1,Volume=1000+i))
    return pd.DataFrame(rows)


class TemporalTests(unittest.TestCase):
    def test_aggregate_ohlcv_and_bar_end(self):
        raw=minute_data();b=aggregate_minutes(raw);g=raw[raw.Ticker.eq('AAA')].iloc[:5];r=b.iloc[0]
        self.assertEqual(r.Open,g.Open.iloc[0]);self.assertEqual(r.Close,g.Close.iloc[-1]);self.assertEqual(r.High,g.High.max());self.assertEqual(r.Low,g.Low.min());self.assertEqual(r.Volume,g.Volume.sum())
        self.assertEqual(r.Bar_End,r.Date+pd.Timedelta(minutes=5));require_complete_sessions(b)

    def test_15_and_30_min_aggregation(self):
        for m in (15,30):
            b=aggregate_minutes(minute_data(),m);self.assertEqual(len(b),2*390//m);require_complete_sessions(b)

    def test_partial_and_missing_bars_not_shifted(self):
        raw=minute_data().drop(index=3);b=aggregate_minutes(raw)
        with self.assertRaises(ValueError):require_complete_sessions(b)

    def test_vwap_opening_range_and_daily_context_causal(self):
        b=aggregate_minutes(minute_data());d=daily_data();f,_=intraday_features(b,d)
        r=f[f.Ticker.eq('AAA')].iloc[0];bar=b.iloc[0]
        self.assertAlmostEqual(r.distance_vwap,bar.Close/(bar.DollarVolume/bar.Volume)-1)
        g=f[f.Ticker.eq('AAA')]
        self.assertTrue(g.or30_distance.iloc[:5].isna().all());self.assertTrue(pd.notna(g.or30_distance.iloc[5]))
        self.assertTrue((f.Daily_Date<f.Join_Date).all())
        modified=b.copy();future=modified.Date.gt(b.Date.min()+pd.Timedelta(minutes=60));modified.loc[future,['Open','High','Low','Close','DollarVolume']]*=10
        other,_=intraday_features(modified,d)
        past=f.Date.le(b.Date.min()+pd.Timedelta(minutes=60))
        pd.testing.assert_series_equal(f.loc[past,'distance_vwap'],other.loc[past,'distance_vwap'])
        pd.testing.assert_series_equal(f.loc[past,'or30_distance'],other.loc[past,'or30_distance'])

    def test_daily_same_day_close_never_used(self):
        b=aggregate_minutes(minute_data());d=daily_data();f,n=intraday_features(b,d)
        altered=d.copy();altered.loc[altered.Date.ge('2024-11-27'),['Open','High','Low','Close']]*=3
        other,_=intraday_features(b,altered)
        cols=[x for x in n if x.startswith('daily_')]
        pd.testing.assert_frame_equal(f[cols],other[cols])

    def test_relative_volume_prior_sessions_only(self):
        b=aggregate_minutes(minute_data(('2024-11-20','2024-11-21','2024-11-22','2024-11-25')))
        f,_=intraday_features(b,daily_data());g=f[f.Ticker.eq('AAA')&f.Session.eq('2024-11-25')]
        self.assertAlmostEqual(g.relative_volume.iloc[0],1.)
        changed=b.copy();later=changed.Session.eq('2024-11-25')&changed.Date.gt(g.Date.iloc[0]);changed.loc[later,'Volume']*=100
        other,_=intraday_features(changed,daily_data());self.assertEqual(other.loc[g.index[0],'relative_volume'],g.relative_volume.iloc[0])

    def test_daily_future_invariance_and_cross_section(self):
        d=daily_data();f,n=daily_features(d);alter=d.copy();alter.loc[alter.Date.gt('2024-01-01'),['Open','High','Low','Close']]*=5
        other,_=daily_features(alter);past=f.Date.le('2024-01-01')
        pd.testing.assert_frame_equal(f.loc[past,n],other.loc[past,n])

    def test_next_open_horizons_and_split_purge(self):
        f=daily_data();lab=Lab(f,'swing',['2024-01-01','2024-01-10'],[1,3],.002)
        ix=lab.select(np.ones(lab.n,bool),3);t,_=lab.details(ix,3)
        self.assertTrue((pd.to_datetime(t.Entry)>pd.to_datetime(t.Signal)).all())
        self.assertTrue((pd.to_datetime(t.Exit)<=pd.Timestamp('2024-01-10')).all())
        for i in ix:self.assertEqual(lab.exits[3][i]-lab.entry[i]+1,3)
        self.assertTrue(lab.f.Date.max()<=pd.Timestamp('2024-01-10'))

    def test_costs_manual_and_no_overlap(self):
        f=daily_data();lab=Lab(f,'swing',['2024-01-01','2024-01-31'],[3],.002)
        ix=lab.select(np.ones(lab.n,bool),3);t,_=lab.details(ix,3)
        np.testing.assert_allclose(t.Gross-t.Net,.002)
        for _,g in t.groupby('Ticker'):self.assertTrue((pd.to_datetime(g.Entry).iloc[1:].to_numpy()>pd.to_datetime(g.Exit).iloc[:-1].to_numpy()).all())
        i=ix[0];self.assertAlmostEqual(t.Net.iloc[0],lab.f.Close.iloc[i+3]/lab.f.Open.iloc[i+1]-1-.002)

    def test_intraday_early_close_no_overnight(self):
        b=aggregate_minutes(minute_data(('2024-11-29',),end='13:00'));require_complete_sessions(b)
        lab=Lab(b,'intraday',['2024-11-29','2024-11-29'],[0,12],.0009)
        for h in (0,12):
            ix=lab.select(np.ones(lab.n,bool),h);t,_=lab.details(ix,h)
            entry=pd.to_datetime(t.Entry,utc=True).dt.tz_convert('America/New_York');ex=pd.to_datetime(t.Exit,utc=True).dt.tz_convert('America/New_York')
            self.assertTrue((entry.dt.date==ex.dt.date).all());self.assertTrue((ex.dt.hour<=13).all());self.assertTrue((t.Holding_Minutes>0).all())
            self.assertTrue((pd.to_datetime(t.Entry,utc=True)>=pd.to_datetime(t.Signal,utc=True)).all())

    def test_two_sessions_cannot_leak_overnight(self):
        bars=aggregate_minutes(minute_data(('2024-11-25','2024-11-26')))
        lab=Lab(bars,'intraday',['2024-11-25','2024-11-26'],[12],.0009)
        mask=np.ones(lab.n,bool);t,_=lab.details(lab.select(mask,12),12)
        entry=pd.to_datetime(t.Entry,utc=True).dt.date;exit=pd.to_datetime(t.Exit,utc=True).dt.date
        self.assertTrue((entry==exit).all())

    def test_entire_missing_session_rejected(self):
        bars=aggregate_minutes(minute_data(('2024-11-20','2024-11-22')))
        with self.assertRaises(ValueError):require_complete_sessions(bars)

    def test_exploration_values_exclude_validation(self):
        f=daily_data();features,names=daily_features(f)
        lab=Lab(features,'swing',['2023-01-01','2023-12-31'],[1,10],.002)
        changed=features.copy();changed.loc[changed.Date.ge('2024-01-01'),'return_10']=999.
        other=Lab(changed,'swing',['2023-01-01','2023-12-31'],[1,10],.002)
        self.assertEqual(lab.f.return_10.quantile(.8),other.f.return_10.quantile(.8))
        self.assertTrue((lab.f.Date<pd.Timestamp('2024-01-01')).all())

    def test_frozen_tamper_and_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'frozen.json';payload={'protocol_sha256':sha(HERE/'protocol.json'),'code_sha256':{},'candidates':[]}
            freeze_file(p,payload);self.assertEqual(load_frozen(p)['candidates'],[])
            with self.assertRaises(FileExistsError):freeze_file(p,payload)
            p.write_text(p.read_text()+' ')
            with self.assertRaises(ValueError):load_frozen(p)

    def test_nan_condition_never_true(self):
        f=pd.DataFrame({'x':[1.,np.nan,2.]});self.assertEqual(rule_mask(f,[dict(feature='x',op='>=',threshold=0)]).tolist(),[True,False,True])

    def test_csv_requires_timezone(self):
        with tempfile.TemporaryDirectory() as d:
            pd.DataFrame({'Date':['2024-01-01 09:30']}).to_csv(Path(d)/'AAA.csv',index=False)
            with self.assertRaises(ValueError):CSVProvider(d).get_bars('AAA','2024-01-01','2024-01-02')

if __name__=='__main__':unittest.main()
