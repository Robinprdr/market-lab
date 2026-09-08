"""Fixed Pullback Long A/B factor study. No optimization or extra filters.

From repo root: python -B research/pullback/pullback_long_v1_research.py
  --ohlc-csv PATH_TO_OHLC --output-dir results/pullback/initial
Dependencies: numpy, pandas. Existing core defines the evaluation universe.
A: Close>SMA50, SMA20>SMA50, Return_20D>0, Return_3D<0.
B: A AND Close>=SMA50 independently on t-2,t-1,t (equality allowed).
Signal at close t; enter Open[t+1]; return Close[t+h]/Open[t+1]-1.
1D/3D primary; 5D secondary. Returns positive are favorable to LONG.
An episode is a maximal consecutive run of Return_3D<0, not a trade.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

CORE_SHA = "ce157c4630580cf431a841af42c18db627c68bee"
HORIZONS = (1, 3, 5)


def rules(x):
    a = x.Close.gt(x.SMA50) & x.SMA20.gt(x.SMA50) & x.Return_20D.gt(0) & x.Return_3D.lt(0)
    valid_above = x.Close.ge(x.SMA50) & x.SMA50.notna()
    held = valid_above.rolling(3, min_periods=3).sum().eq(3)
    return a, a & held


def features(frame):
    x = frame.sort_values("Date").reset_index(drop=True).copy()
    x["Session"] = np.arange(len(x))
    x["SMA20"] = x.Close.rolling(20).mean()
    x["SMA50"] = x.Close.rolling(50).mean()
    for h in (1, 3, 10, 20):
        x[f"Return_{h}D"] = x.Close.pct_change(h, fill_method=None)
    x["Distance_SMA50"] = x.Close / x.SMA50 - 1
    x["SMA20_vs_SMA50"] = x.SMA20 / x.SMA50 - 1
    x["A"], x["B"] = rules(x)
    for lag in (1, 2):
        x[f"Close_Lag{lag}"] = x.Close.shift(lag)
        x[f"SMA50_Lag{lag}"] = x.SMA50.shift(lag)
    negative = x.Return_3D.lt(0)
    starts = negative & ~negative.shift(1, fill_value=False)
    x["Episode_Start"] = x.Date.where(starts).ffill().where(negative)
    return x


def tests():
    # A can hold today while t-1 or t-2 was below its own SMA50.
    x = pd.DataFrame({"Close": [102., 99., 102.], "SMA50": [100., 100., 100.],
                      "SMA20": [101.]*3, "Return_20D": [.1]*3, "Return_3D": [-.01]*3})
    a, b = rules(x)
    assert a.iloc[-1] and not b.iloc[-1]
    x.loc[1, "Close"] = 100.  # no close below: equality is accepted
    assert rules(x)[1].iloc[-1]
    x.loc[0, "Close"] = 99.
    assert not rules(x)[1].iloc[-1]
    x.loc[0, "Close"] = 102.
    x.loc[0, "SMA50"] = 103.  # compare to each session's own SMA50
    assert not rules(x)[1].iloc[-1]
    for col, value in (("Close", 100.), ("SMA20", 100.), ("Return_20D", 0.), ("Return_3D", 0.)):
        y = x.copy()
        y.loc[2, col] = value
        assert not rules(y)[0].iloc[-1]


def validate_causality(x):
    c = x.Close.to_numpy()
    ea, eb = np.zeros(len(x), bool), np.zeros(len(x), bool)
    for i in range(49, len(x)):
        ea[i] = c[i] > c[i-49:i+1].mean() and c[i-19:i+1].mean() > c[i-49:i+1].mean() and c[i] > c[i-20] and c[i] < c[i-3]
        if i >= 51:
            eb[i] = ea[i] and all(c[j] >= c[j-49:j+1].mean() for j in (i-2, i-1, i))
    assert np.array_equal(ea, x.A) and np.array_equal(eb, x.B)
    for cutoff in (60, len(x)//2, len(x)-5):
        prefix = features(x.iloc[:cutoff])
        assert np.array_equal(prefix[["A", "B"]], x[["A", "B"]].iloc[:cutoff])
    cutoff = len(x)//2
    altered = x.copy()
    altered.loc[cutoff:, ["Open", "High", "Low", "Close"]] *= 7
    assert np.array_equal(features(altered)[["A", "B"]].iloc[:cutoff], x[["A", "B"]].iloc[:cutoff])


def stats(x, group, year="ALL"):
    return [{"Group": group, "Year": year, "Horizon": h, "Observations": len(x),
             "Mean": x[f"Future_Return_{h}D"].mean(), "Median": x[f"Future_Return_{h}D"].median(),
             "Positive_Fraction": x[f"Future_Return_{h}D"].gt(0).mean() if len(x) else np.nan}
            for h in HORIZONS]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core-csv", type=Path, default=Path("results/short_momentum/short_momentum_v1_research_core.csv"))
    p.add_argument("--ohlc-csv", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("results/pullback/initial"))
    args = p.parse_args()
    tests()
    blob = args.core_csv.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest() == CORE_SHA
    core = pd.read_csv(args.core_csv, parse_dates=["Date"])
    raw = pd.read_csv(args.ohlc_csv, parse_dates=["Date"])
    assert not core.duplicated(["Date", "Ticker"]).any() and not raw.duplicated(["Date", "Ticker"]).any()
    assert set(core.Ticker) == set(raw.Ticker)
    assert not raw[["Open", "High", "Low", "Close"]].isna().any().any()
    assert (raw[["Open", "High", "Low", "Close"]] > 0).all().all()
    assert not core[[f"Future_Return_{h}D" for h in HORIZONS]].isna().any().any()
    frames = []
    for ticker, group in raw.groupby("Ticker"):
        x = features(group)
        validate_causality(x)
        # Signal already computed; only now add future fields for evaluation.
        x["Entry_Date"] = x.Date.shift(-1)
        x["Entry_Open"] = x.Open.shift(-1)
        for h in HORIZONS:
            x[f"Exit_Date_{h}D"] = x.Date.shift(-h)
            x[f"Future_Return_{h}D"] = x.Close.shift(-h) / x.Open.shift(-1) - 1
        for i in np.flatnonzero(x.A.to_numpy()):
            if i + 5 >= len(x):
                continue
            assert x.Entry_Date.iloc[i] == x.Date.iloc[i+1]
            assert x.Entry_Open.iloc[i] == x.Open.iloc[i+1]
            for h in HORIZONS:
                assert x[f"Exit_Date_{h}D"].iloc[i] == x.Date.iloc[i+h]
                assert abs(x[f"Future_Return_{h}D"].iloc[i] - (x.Close.iloc[i+h]/x.Open.iloc[i+1]-1)) < 1e-12
        frames.append(x)
    d = core.merge(pd.concat(frames), on=["Date", "Ticker"], how="left", suffixes=("", "_Rebuilt"), validate="one_to_one", indicator=True)
    assert d._merge.eq("both").all()
    reconciliation = {}
    for col in ["Return_1D", "Return_3D", "Return_10D", "Return_20D", "Distance_SMA50", "SMA20_vs_SMA50"] + [f"Future_Return_{h}D" for h in HORIZONS]:
        a, b = d[col], d[col+"_Rebuilt"]
        assert np.isclose(a, b, equal_nan=True, rtol=1e-7, atol=1e-6).all()
        assert a.gt(0).equals(b.gt(0)) and a.lt(0).equals(b.lt(0))
        reconciliation[col] = float((a-b).abs().max())
    assert not (d.B & ~d.A).any()
    d["Year"] = d.Date.dt.year
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics = stats(d, "BASELINE")
    for year, z in d.groupby("Year"):
        metrics += stats(z, "BASELINE", int(year))
    counts = d.groupby("Year").size().rename("Baseline_Observations").to_frame()
    summary = {"core_git_blob": CORE_SHA, "ohlc_sha256": hashlib.sha256(args.ohlc_csv.read_bytes()).hexdigest(),
               "baseline_rows": len(d), "first_date": str(d.Date.min().date()), "last_date": str(d.Date.max().date()),
               "intersection": int((d.A & d.B).sum()), "A_only": int((d.A & ~d.B).sum()), "B_only": int((d.B & ~d.A).sum()),
               "B_excluded_missing_prior_SMA50": int((d.A & ~d.B & d[["SMA50_Lag1", "SMA50_Lag2"]].isna().any(axis=1)).sum()),
               "B_excluded_prior_close_below_SMA50": int((d.A & ~d.B & ((d.Close_Lag1 < d.SMA50_Lag1) | (d.Close_Lag2 < d.SMA50_Lag2))).sum()),
               "reconciliation_max_abs_differences": reconciliation, "groups": {}}
    for name in ("A", "B"):
        x = d[d[name]].copy().sort_values(["Ticker", "Date"])
        metrics += stats(x, name)
        for year in sorted(d.Year.unique()):
            z = x[x.Year.eq(year)]
            metrics += stats(z, name, int(year))
        for label, series in (("Observations", x.groupby("Year").size()), ("Tickers", x.groupby("Year").Ticker.nunique()), ("Dates", x.groupby("Year").Date.nunique())):
            counts[f"{name}_{label}"] = series.reindex(counts.index, fill_value=0)
        episode_sizes = x.groupby(["Ticker", "Episode_Start"]).size()
        gaps = x.groupby("Ticker").Session.diff()
        holds = {}
        for h in HORIZONS:
            retained = 0
            for _, z in x.groupby("Ticker"):
                last = -100000
                for session in z.Session:
                    if session-last >= h:
                        retained += 1
                        last = session
            holds[str(h)] = {"retained": retained, "excluded": len(x)-retained, "overlaps_previous_signal": int(gaps.lt(h).sum())}
        summary["groups"][name] = {"observations": len(x), "mean_per_year": len(x)/d.Year.nunique(), "tickers": int(x.Ticker.nunique()), "dates": int(x.Date.nunique()),
                                   "episodes": len(episode_sizes), "episodes_with_multiple_observations": int(episode_sizes.gt(1).sum()),
                                   "observations_beyond_first_per_episode": int((episode_sizes-1).sum()), "max_observations_per_episode": int(episode_sizes.max()),
                                   "consecutive_same_ticker_observations": int(gaps.eq(1).sum()), "holds": holds}
    pd.DataFrame(metrics).to_csv(args.output_dir/"statistics.csv", index=False)
    counts.to_csv(args.output_dir/"annual_counts.csv")
    keep = ["Date", "Ticker", "A", "B", "Episode_Start", "Session", "Close", "SMA20", "SMA50", "Close_Lag1", "SMA50_Lag1", "Close_Lag2", "SMA50_Lag2", "Return_20D", "Return_3D", "Entry_Date", "Entry_Open"]
    keep += [f"Future_Return_{h}D" for h in HORIZONS] + [f"Exit_Date_{h}D" for h in HORIZONS]
    d.loc[d.A, keep].to_csv(args.output_dir/"observations.csv", index=False)
    summary["checks"] = "A/B boundary tests, independent scalar implementation, prefix invariance, future mutation, entry/exit alignment, source reconciliation passed"
    (args.output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(metrics).to_string(index=False))
    print(counts.to_string())


if __name__ == "__main__":
    main()
