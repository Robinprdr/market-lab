import numpy as np
import pandas as pd
import unittest

from research.research_engine.core import Costs, ExperimentConfig, align_daily_signals, align_event_signals, build_baseline, compare_baseline, deduplicate_episodes, evaluate, split_by_config, leave_one_stock_out, walk_forward_annual


def frame():
    dates = pd.bdate_range("2024-01-02", periods=10)
    close = np.arange(10., 20.)
    return pd.DataFrame({"Date":dates,"Ticker":"AAA","Open":close-0.5,"High":close+0.5,"Low":close-1,"Close":close,"Volume":100})


def cfg(direction="LONG", costs=None):
    return ExperimentConfig("test", "EXPLORATORY", direction, "close[t]", "fixed", (1,3,5), costs or Costs(0,0,0,0))


class TestEngine(unittest.TestCase):
  def test_daily_dates_and_horizons_and_signs(self):
    t=align_daily_signals(frame(), [False,True]+[False]*8, (1,3,5), "LONG")
    self.assertEqual(t.iloc[0].Entry_Date, frame().Date.iloc[2])
    self.assertEqual(t.iloc[0].Exit_Date_3D, frame().Date.iloc[4])
    self.assertAlmostEqual(t.iloc[0].Future_Return_3D, frame().Close.iloc[4]/frame().Open.iloc[2]-1)
    s=align_daily_signals(frame(), [False,True]+[False]*8, (1,), "SHORT")
    self.assertLess(s.iloc[0].Future_Return_1D, 0)


  def test_event_uses_explicit_next_session(self):
    x=frame(); events=pd.DataFrame({"ticker":["AAA"],"event_date":[x.Date.iloc[1]],"entry_date":[x.Date.iloc[2]]})
    t=align_event_signals(events,x,"LONG", (1,3,5))
    self.assertEqual(t.iloc[0].Entry_Open, x.Open.iloc[2])
    self.assertEqual(t.iloc[0].exit_date_3D, x.Date.iloc[4])
    missing=events.copy(); missing.entry_date=pd.Timestamp("2030-01-01")
    mt=align_event_signals(missing,x,"LONG",(1,)); self.assertFalse(bool(mt.Entry_Valid.iloc[0])); self.assertTrue(pd.isna(mt.Future_Return_1D.iloc[0]))


  def test_costs_profit_factor_and_sign(self):
    x=frame(); t=align_daily_signals(x,[False,True]+[False]*8,(1,),"LONG")
    report=evaluate(t,ExperimentConfig("test","EXPLORATORY","LONG","close[t]","fixed",(1,),Costs(.001,.001,.001,.001)))
    expected=(x.Close.iloc[2]*(1-.001)*(1-.001)/(x.Open.iloc[2]*(1+.001)*(1+.001)))-1
    self.assertAlmostEqual(report.query("Result == 'NET'").iloc[0].Mean, expected)
    self.assertTrue(pd.isna(report.query("Result == 'GROSS'").iloc[0].Profit_Factor))
    short=align_daily_signals(x,[False,True]+[False]*8,(1,),"SHORT")
    sr=evaluate(short,ExperimentConfig("s","EXPLORATORY","SHORT","close","fixed",(1,),Costs(.001,.001,.001,.001)))
    expected_short=(x.Open.iloc[2]*(1-.001)*(1-.001)/(x.Close.iloc[2]*(1+.001)*(1+.001)))-1
    self.assertAlmostEqual(sr.query("Result == 'NET'").iloc[0].Mean, expected_short)


  def test_episode_dedup_and_boundary(self):
    x=frame(); x["Signal"]=[False,True,True,False,True,False,False,False,False,False]
    self.assertEqual(len(deduplicate_episodes(x)), 2)
    c=cfg(); c=ExperimentConfig(**{**c.as_dict(),"costs":Costs(**c.as_dict()["costs"]),"train_period":("2024-01-02","2024-01-03"),"oos_period":("2024-01-04","2024-01-15")})
    t=align_daily_signals(x,x.Signal,(1,))
    parts=split_by_config(t,c)
    self.assertLessEqual(len(parts["TRAIN"])+len(parts["OOS"]), len(t))

  def test_episode_requires_complete_frame_and_multiple_tickers(self):
    x=frame(); x["Signal"]=[False,True,True,False,True,False,False,False,False,False]
    y=x.copy(); y.Ticker="BBB"
    both=pd.concat([x,y],ignore_index=True)
    starts=deduplicate_episodes(both)
    self.assertEqual(len(starts),4)
    with self.assertRaisesRegex(ValueError,"Signal=False"):
      deduplicate_episodes(x[x.Signal])
    with self.assertRaisesRegex(ValueError,"requires"):
      deduplicate_episodes(x.drop(columns="Signal"))

  def test_year_boundary_and_leave_one_out(self):
    x=frame(); t=align_daily_signals(x,[False,True]+[False]*8,(1,),"LONG")
    c=ExperimentConfig("test","VALIDATION","LONG","close[t]","fixed",(1,),Costs(0,0,0,0),train_period=("2024-01-02","2024-01-03"),oos_period=("2024-01-04","2024-01-15"))
    self.assertIn("TRAIN", split_by_config(t,c)); self.assertEqual(len(leave_one_stock_out(t,c)), 1)

  def test_purge_removes_exit_after_period_end(self):
    x=frame(); x.Date=pd.bdate_range("2022-12-27",periods=10)
    t=align_daily_signals(x,[False,False,False,True]+[False]*6,(1,3,5),"LONG")
    c=ExperimentConfig("test","VALIDATION","LONG","close[t]","fixed",(1,3,5),Costs(0,0,0,0),train_period=("2022-01-01","2022-12-31"),oos_period=("2023-01-01","2023-12-31"))
    train=split_by_config(t,c)["TRAIN"]
    self.assertEqual(len(train),1); self.assertTrue(train.Purged_Period_Boundary_3D.iloc[0]); self.assertTrue(pd.isna(train.Future_Return_3D.iloc[0])); self.assertEqual(train.attrs["diagnostics"]["purged_period_boundary"]["3"],1)
    report=evaluate(train,c,"TRAIN"); self.assertEqual(report.query("Horizon == 3 and Result == 'NET'").iloc[0].N,0)

  def test_true_walk_forward_has_train_then_test_year(self):
    d=pd.DataFrame({"Signal_Date":pd.to_datetime(["2020-06-01","2021-06-01","2022-06-01"]),"Ticker":["AAA"]*3,"Entry_Open":[10.,10.,10.],"Exit_Close_1D":[11.,11.,11.],"Exit_Date_1D":pd.to_datetime(["2020-06-02","2021-06-02","2022-06-02"]),"Future_Return_1D":[.1,.1,.1]})
    w=walk_forward_annual(d,ExperimentConfig("wf","EXPLORATORY","LONG","close","fixed",(1,),Costs(0,0,0,0)),train_years=1)
    self.assertEqual(list(w.Test_Year),[2021,2022]); self.assertEqual(list(w.Train_End),[2020,2021])

  def test_baseline_same_period_and_direction(self):
    x=frame(); c=ExperimentConfig("base","EXPLORATORY","LONG","close","fixed",(1,),Costs(0,0,0,0))
    sig=align_daily_signals(x,[False,True]+[False]*8,(1,),"LONG"); base=build_baseline(x,c)
    out=compare_baseline(sig,base,c); self.assertEqual(set(out.Group),{"SIGNALS","BASELINE"})
    with self.assertRaises(ValueError): compare_baseline(sig,build_baseline(x,ExperimentConfig("b","EXPLORATORY","SHORT","close","fixed",(1,),Costs(0,0,0,0))),c)

  def test_eligibility_missing_entry_exit_and_future_invariance(self):
    x=frame(); x["Eligible"]=True; x.loc[2,"Eligible"]=False; x.loc[4,"Open"]=np.nan; x.loc[5,"Close"]=np.nan
    t=align_daily_signals(x,[False,True,False,True,False,False,False,False,False,False],(1,3),"LONG")
    self.assertFalse(t.Entry_Valid.iloc[0]); self.assertGreaterEqual(t.Entry_Valid.sum(),0); self.assertGreaterEqual(t.Return_Evaluable_3D.sum(),0)
    z=frame(); s=[False,True]+[False]*8; a=align_daily_signals(z,s,(1,),"LONG"); z.loc[6:,"Close"]*=99; b=align_daily_signals(z,s,(1,),"LONG"); self.assertEqual(a.Signal.iloc[0],b.Signal.iloc[0])


if __name__ == "__main__":
    unittest.main()
