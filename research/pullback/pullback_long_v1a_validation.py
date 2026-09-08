"""Frozen A validation: one rising-edge signal per contiguous A episode.
No fitting/optimization. Train 2018-2021, retrospective OOS 2022-2025.
Annual walk-forward 2021-2025 with preceding 3 calendar years as train.
Signal t, next-session Open entry, Close[t+h] exit. Purge each horizon's
exits beyond the evaluated window. Never reset episode state at a split.
Fees and slippage each 0.0005 per side; net return on total entry outlay.
Contribution sums assume $1 entry outlay per signal: NOT a portfolio curve.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5)
FEE = SLIPPAGE = 0.0005
COST_MULTIPLIER = (1-SLIPPAGE)*(1-FEE)/((1+SLIPPAGE)*(1+FEE))
CORE_SHA = "ce157c4630580cf431a841af42c18db627c68bee"


def rising_edges(a):
    return a & ~a.shift(1, fill_value=False)


def features(frame):
    x = frame.sort_values("Date").reset_index(drop=True).copy()
    x["Session"] = np.arange(len(x))
    x["SMA20"] = x.Close.rolling(20).mean()
    x["SMA50"] = x.Close.rolling(50).mean()
    x["Return_20D"] = x.Close.pct_change(20, fill_method=None)
    x["Return_3D"] = x.Close.pct_change(3, fill_method=None)
    x["A"] = x.Close.gt(x.SMA50) & x.SMA20.gt(x.SMA50) & x.Return_20D.gt(0) & x.Return_3D.lt(0)
    x["Signal"] = rising_edges(x.A)
    x["Episode_Number"] = x.Signal.cumsum().where(x.A)
    return x


def checks(x):
    c = x.Close.to_numpy()
    expected = np.zeros(len(x), bool)
    for i in range(49, len(x)):
        expected[i] = c[i]>c[i-49:i+1].mean() and c[i-19:i+1].mean()>c[i-49:i+1].mean() and c[i]>c[i-20] and c[i]<c[i-3]
    assert np.array_equal(expected, x.A)
    assert np.array_equal(expected & ~np.r_[False, expected[:-1]], x.Signal)
    for end in (60, len(x)//2, len(x)-5):
        assert np.array_equal(features(x.iloc[:end]).Signal, x.Signal.iloc[:end])
    cut = len(x)//2
    changed = x.copy()
    changed.loc[cut:, ["Open", "High", "Low", "Close"]] *= 7
    assert np.array_equal(features(changed).Signal.iloc[:cut], x.Signal.iloc[:cut])


def evaluate(x, label, start, end, group):
    rows = []
    for h in HORIZONS:
        candidates = x[(x.Date>=start)&(x.Date<end)]
        z = candidates[candidates[f"Exit_Date_{h}D"]<end]
        assert z.Entry_Date.ge(start).all()
        gross, net = z[f"Future_Return_{h}D"], z[f"Net_Return_{h}D"]
        rows.append({"Period":label,"Group":group,"Start":start,"End_Exclusive":end,"Horizon":h,
                     "Signals_Before_Purge":len(candidates),"Purged":len(candidates)-len(z),"N":len(z),
                     "Gross_Mean":gross.mean(),"Gross_Median":gross.median(),"Gross_Win_Rate":gross.gt(0).mean(),
                     "Net_Mean":net.mean(),"Net_Median":net.median(),"Net_Win_Rate":net.gt(0).mean(),
                     "Net_Contribution_Sum":net.sum()})
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core-csv",type=Path,default=Path("results/short_momentum/short_momentum_v1_research_core.csv"))
    p.add_argument("--ohlc-csv",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,default=Path("results/pullback/v1a_validation"))
    args=p.parse_args()
    assert rising_edges(pd.Series([False,True,True,False,True,True,False,True])).tolist()==[False,True,False,False,True,False,False,True]
    assert np.isclose(COST_MULTIPLIER-1,-0.001998001499000645,atol=1e-12)
    blob=args.core_csv.read_bytes()
    assert hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()==CORE_SHA
    core=pd.read_csv(args.core_csv,parse_dates=["Date"])
    raw=pd.read_csv(args.ohlc_csv,parse_dates=["Date"])
    assert not raw.duplicated(["Ticker","Date"]).any() and not core.duplicated(["Ticker","Date"]).any()
    assert set(raw.Ticker)==set(core.Ticker)
    assert not raw[["Open","High","Low","Close"]].isna().any().any()
    assert (raw[["Open","High","Low","Close"]]>0).all().all()
    frames=[]
    for ticker,group in raw.groupby("Ticker"):
        x=features(group)
        checks(x)
        x["Entry_Date"]=x.Date.shift(-1)
        x["Entry_Open"]=x.Open.shift(-1)
        for h in HORIZONS:
            x[f"Exit_Date_{h}D"]=x.Date.shift(-h)
            x[f"Exit_Close_{h}D"]=x.Close.shift(-h)
            x[f"Future_Return_{h}D"]=x.Close.shift(-h)/x.Open.shift(-1)-1
        for i in np.flatnonzero(x.Signal):
            if i+5>=len(x): continue
            assert x.Entry_Date.iloc[i]==x.Date.iloc[i+1] and x.Entry_Open.iloc[i]==x.Open.iloc[i+1]
            for h in HORIZONS:
                assert x[f"Exit_Date_{h}D"].iloc[i]==x.Date.iloc[i+h]
                assert abs(x[f"Future_Return_{h}D"].iloc[i]-(x.Close.iloc[i+h]/x.Open.iloc[i+1]-1))<1e-12
        frames.append(x)
    d=core.merge(pd.concat(frames),on=["Date","Ticker"],how="left",suffixes=("","_Rebuilt"),validate="one_to_one",indicator=True)
    assert d._merge.eq("both").all()
    for h in HORIZONS:
        assert np.allclose(d[f"Future_Return_{h}D"],d[f"Future_Return_{h}D_Rebuilt"],rtol=0,atol=1e-12)
        d[f"Net_Return_{h}D"]=(1+d[f"Future_Return_{h}D"])*COST_MULTIPLIER-1
        direct=(d[f"Exit_Close_{h}D"]*(1-SLIPPAGE)*(1-FEE))/(d.Entry_Open*(1+SLIPPAGE)*(1+FEE))-1
        assert np.allclose(direct,d[f"Net_Return_{h}D"],rtol=0,atol=1e-12)
    # The recomputed A agrees with the original core factors, without any new rule.
    core_a=d.Distance_SMA50.gt(0)&d.SMA20_vs_SMA50.gt(0)&d.Return_20D.gt(0)&d.Return_3D.lt(0)
    assert np.array_equal(core_a,d.A)
    signals=d[d.Signal].sort_values(["Ticker","Date"]).copy()
    assert not signals.duplicated(["Ticker","Episode_Number"]).any()
    assert signals.Entry_Date.gt(signals.Date).all()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    periods=[("GLOBAL","2018-01-01","2026-01-01"),("TRAIN","2018-01-01","2022-01-01"),("OOS","2022-01-01","2026-01-01")]
    rows=[]
    for label,start,end in periods:
        rows+=evaluate(signals,label,start,end,"A_FIRST")
        rows+=evaluate(d,label,start,end,"BASELINE")
    pd.DataFrame(rows).to_csv(args.output_dir/"period_statistics.csv",index=False)
    annual=[]
    for year in range(2018,2026):
        for name,x in (("A_FIRST",signals),("BASELINE",d)):
            annual+=evaluate(x,str(year),f"{year}-01-01",f"{year+1}-01-01",name)
    pd.DataFrame(annual).to_csv(args.output_dir/"annual_statistics.csv",index=False)
    wf=[]
    for year in range(2021,2026):
        for role,start,end in (("TRAIN",f"{year-3}-01-01",f"{year}-01-01"),("TEST",f"{year}-01-01",f"{year+1}-01-01")):
            for name,x in (("A_FIRST",signals),("BASELINE",d)):
                wf += [dict(row,Fold=year,Role=role) for row in evaluate(x,f"WF_{year}",start,end,name)]
    wf=pd.DataFrame(wf)
    wf.to_csv(args.output_dir/"walk_forward.csv",index=False)
    # Tests don't overlap each other. Training windows do: never pool train returns.
    wf_totals=[]
    for h in HORIZONS:
        for name,x in (("A_FIRST",signals),("BASELINE",d)):
            masks=pd.Series(False,index=x.index)
            for year in range(2021,2026):
                masks |= (x.Date>=f"{year}-01-01")&(x.Date<f"{year+1}-01-01")&(x[f"Exit_Date_{h}D"]<f"{year+1}-01-01")
            z=x[masks]
            wf_totals.append({"Group":name,"Horizon":h,"N":len(z),"Gross_Mean":z[f"Future_Return_{h}D"].mean(),"Net_Mean":z[f"Net_Return_{h}D"].mean(),"Net_Median":z[f"Net_Return_{h}D"].median(),"Net_Win_Rate":z[f"Net_Return_{h}D"].gt(0).mean()})
    pd.DataFrame(wf_totals).to_csv(args.output_dir/"walk_forward_summary.csv",index=False)
    concentration=[]; robustness=[]; loso=[]
    for label,start,end in (periods[0],periods[2]):
        x=signals[(signals.Date>=start)&(signals.Date<end)&(signals.Exit_Date_3D<end)]
        c=x.groupby("Ticker").Net_Return_3D.agg(N="size",Net_Mean="mean",Net_Contribution="sum").sort_values("Net_Contribution",ascending=False)
        c["Period"]=label
        concentration.append(c.reset_index())
        positive_sum=c.Net_Contribution.clip(lower=0).sum()
        for k in (0,1,3,5):
            removed=list(c.index[:k])
            z=x[~x.Ticker.isin(removed)]
            robustness.append({"Period":label,"Removed_Top":k,"Removed_Tickers":",".join(removed),"N":len(z),"Net_Mean_3D":z.Net_Return_3D.mean(),"Net_Win_Rate_3D":z.Net_Return_3D.gt(0).mean(),"Top_Share_Positive_Ticker_Contributions":c.Net_Contribution.iloc[:k].clip(lower=0).sum()/positive_sum if positive_sum else None})
        for ticker in sorted(x.Ticker.unique()):
            z=x[x.Ticker!=ticker]
            loso.append({"Period":label,"Removed_Ticker":ticker,"N":len(z),"Net_Mean_3D":z.Net_Return_3D.mean()})
    pd.concat(concentration).to_csv(args.output_dir/"ticker_concentration_3d.csv",index=False)
    pd.DataFrame(robustness).to_csv(args.output_dir/"remove_top_contributors_3d.csv",index=False)
    pd.DataFrame(loso).to_csv(args.output_dir/"leave_one_stock_out_3d.csv",index=False)
    yc=signals.groupby(signals.Date.dt.year).Net_Return_3D.agg(N="size",Net_Mean="mean",Net_Contribution="sum")
    yc.to_csv(args.output_dir/"year_contribution_3d.csv")
    counts=signals.groupby(signals.Date.dt.year).agg(Signals=("Ticker","size"),Tickers=("Ticker","nunique"),Dates=("Date","nunique"))
    counts.to_csv(args.output_dir/"annual_counts.csv")
    keys=["Date","Ticker","Session","Episode_Number","Close","SMA20","SMA50","Return_20D","Return_3D","Entry_Date","Entry_Open"]
    keys += [f"{prefix}_{h}D" for h in HORIZONS for prefix in ("Exit_Date","Exit_Close","Future_Return","Net_Return")]
    signals[keys].to_csv(args.output_dir/"signals.csv",index=False)
    summary={"core_sha":CORE_SHA,"ohlc_sha256":hashlib.sha256(args.ohlc_csv.read_bytes()).hexdigest(),"signals":len(signals),"tickers":int(signals.Ticker.nunique()),"dates":int(signals.Date.nunique()),"original_A_observations":int(d.A.sum()),"removed_repeated_A_observations":int(d.A.sum())-len(signals),"duplicate_episodes":0,"cost_multiplier":COST_MULTIPLIER,"flat_price_net_return":COST_MULTIPLIER-1,"costs_each_side":{"fee":FEE,"slippage":SLIPPAGE},"overlaps_with_previous_episode_signal":{str(h):int(signals.groupby("Ticker").Session.diff().lt(h).sum()) for h in HORIZONS},"checks":"rising edges, scalar rule equivalence, future mutation, prefix invariance, exact horizon alignment, cost reconciliation passed","limitation":"retrospective OOS; these calendar years were already inspected in initial research; no training or re-optimization"}
    (args.output_dir/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))
    for name in ("period_statistics.csv","annual_counts.csv","annual_statistics.csv","walk_forward_summary.csv","remove_top_contributors_3d.csv","year_contribution_3d.csv"):
        print(name);print(pd.read_csv(args.output_dir/name).to_string(index=False))


if __name__=="__main__": main()
