import numpy as np
import pandas as pd
import unittest

from research.research_engine.core import Costs, ExperimentConfig, align_daily_signals, align_event_signals, deduplicate_episodes, evaluate, split_by_config, leave_one_stock_out


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


  def test_costs_profit_factor_and_sign(self):
    x=frame(); t=align_daily_signals(x,[False,True]+[False]*8,(1,),"LONG")
    report=evaluate(t,ExperimentConfig("test","EXPLORATORY","LONG","close[t]","fixed",(1,),Costs(.001,.001,.001,.001)))
    self.assertAlmostEqual(report.query("Result == 'NET'").iloc[0].Mean, report.query("Result == 'GROSS'").iloc[0].Mean-.004)
    self.assertTrue(pd.isna(report.query("Result == 'GROSS'").iloc[0].Profit_Factor))


  def test_episode_dedup_and_boundary(self):
    x=frame(); x["Signal"]=[False,True,True,False,True,False,False,False,False,False]
    self.assertEqual(len(deduplicate_episodes(x)), 2)
    c=cfg(); c=ExperimentConfig(**{**c.as_dict(),"costs":Costs(**c.as_dict()["costs"]),"train_period":("2024-01-02","2024-01-03"),"oos_period":("2024-01-04","2024-01-15")})
    t=align_daily_signals(x,x.Signal,(1,))
    parts=split_by_config(t,c)
    self.assertLessEqual(len(parts["TRAIN"])+len(parts["OOS"]), len(t))

  def test_year_boundary_and_leave_one_out(self):
    x=frame(); t=align_daily_signals(x,[False,True]+[False]*8,(1,),"LONG")
    c=ExperimentConfig("test","VALIDATION","LONG","close[t]","fixed",(1,),Costs(0,0,0,0),train_period=("2024-01-02","2024-01-03"),oos_period=("2024-01-04","2024-01-15"))
    self.assertIn("TRAIN", split_by_config(t,c)); self.assertEqual(len(leave_one_stock_out(t,c)), 1)


if __name__ == "__main__":
    unittest.main()
