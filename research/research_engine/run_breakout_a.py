"""Reproduce the archived Breakout Long A factor through Research Engine V1."""
from __future__ import annotations

import argparse, hashlib, json, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "breakout"))
from breakout_long_v1_research import features, CORE_SHA  # noqa: E402
from core import Costs, ExperimentConfig, align_daily_signals, evaluate, concentration, leave_one_stock_out, split_by_config, walk_forward_annual  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ohlc-csv", type=Path, default=Path("../bfr_data/yahoo_ohlc_2018_2025.csv"))
    p.add_argument("--core-csv", type=Path, default=Path("results/short_momentum/short_momentum_v1_research_core.csv"))
    p.add_argument("--output-dir", type=Path, default=Path("results/research_engine/breakout_a"))
    args = p.parse_args()
    raw = pd.read_csv(args.ohlc_csv, parse_dates=["Date"])
    frames=[]
    for _, g in raw.groupby("Ticker"):
        x=features(g)
        for h in (1,3,5): x[f"_valid_{h}"]=x.Close.shift(-h).notna() & x.Open.shift(-1).notna()
        frames.append(x)
    data=pd.concat(frames, ignore_index=True)
    # The engine receives only the frozen A condition. No parameter selection
    # occurs here; the archived core is used solely as a reconciliation oracle.
    trades=[]
    for _,g in data.groupby("Ticker"):
        z=align_daily_signals(g, g.A, horizons=(1,3,5), direction="LONG")
        z=z[z[["Future_Return_1D","Future_Return_3D","Future_Return_5D"]].notna().all(axis=1)]
        trades.append(z)
    trades=pd.concat(trades, ignore_index=True)
    # The archived core is the historical evaluation universe (it intentionally
    # ends before rows without all forward horizons). Restricting to its keys
    # makes this a reconciliation, rather than a silently different sample.
    core = pd.read_csv(args.core_csv, parse_dates=["Date"])
    trades = trades.merge(core[["Date", "Ticker", "Future_Return_1D", "Future_Return_3D", "Future_Return_5D"]],
                          on=["Date", "Ticker"], how="inner", suffixes=("", "_archived"), validate="one_to_one")
    for h in (1, 3, 5):
        assert (trades[f"Future_Return_{h}D"] - trades[f"Future_Return_{h}D_archived"]).abs().max() < 1e-12
        trades.drop(columns=f"Future_Return_{h}D_archived", inplace=True)
    assert len(trades) == 7812
    cfg=ExperimentConfig("breakout_long_v1_a_engine_reproduction","EXPLORATORY","LONG","Close[t]","Close[t] > max(High[t-20:t-1])",(1,3,5), costs=Costs(0,0,0,0), episode_rule="none", train_period=("2018-01-01","2022-12-31"), oos_period=("2023-01-01","2025-12-31"))
    stats=evaluate(trades,cfg,"BREAKOUT_A")
    annual=[]
    trades["Year"]=pd.to_datetime(trades.Signal_Date).dt.year
    for year,g in trades.groupby("Year"): annual.append(evaluate(g,cfg,"BREAKOUT_A").assign(Year=int(year)))
    annual=pd.concat(annual,ignore_index=True) if annual else pd.DataFrame()
    ticker,years,conc=concentration(trades,cfg)
    periods=[]
    for name, subset in split_by_config(trades,cfg).items():
        if name != "ALL": periods.append(evaluate(subset,cfg,name))
    periods=pd.concat(periods,ignore_index=True) if periods else pd.DataFrame()
    loo=leave_one_stock_out(trades,cfg)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"config.json").write_text(json.dumps(cfg.as_dict(),indent=2)+"\n")
    stats.to_csv(args.output_dir/"statistics.csv",index=False); annual.to_csv(args.output_dir/"annual_statistics.csv",index=False)
    ticker.to_csv(args.output_dir/"ticker_concentration.csv",index=False)
    periods.to_csv(args.output_dir/"period_statistics.csv",index=False)
    loo.to_csv(args.output_dir/"leave_one_stock_out.csv",index=False)
    wf=walk_forward_annual(trades,cfg); wf.to_csv(args.output_dir/"walk_forward.csv",index=False)
    summary={"observations":len(trades),"tickers":int(trades.Ticker.nunique()),"dates":int(trades.Signal_Date.nunique()),"archived_core_sha":CORE_SHA,"results":stats.to_dict(orient="records"),"concentration":conc,"checks":"engine daily alignment and archived Breakout feature definition passed"}
    (args.output_dir/"summary.json").write_text(json.dumps(summary,indent=2,default=str)+"\n")
    print(json.dumps(summary,indent=2,default=str))


if __name__ == "__main__": main()
