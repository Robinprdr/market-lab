"""Exploratory Gap Down Fade Long V1 study.

This post-hoc hypothesis follows the rejected Gap Continuation V1 results and
is not independent validation. Fixed signal: Open[t]/Close[t-1]-1 <= -2%.
Theoretical LONG entry Open[t]. Returns: Close[t]/Open[t]-1 at 1D,
Close[t+2]/Open[t]-1 at 3D and Close[t+4]/Open[t]-1 at 5D.
No costs, slippage, filters, sizing, exits or threshold optimization.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

THRESHOLD = -0.02
HORIZONS = {1: 0, 3: 2, 5: 4}


def build_ticker(frame):
    x = frame.sort_values("Date").reset_index(drop=True).copy()
    x["Session"] = np.arange(len(x))
    x["Previous_Close"] = x.Close.shift(1)
    x["Gap"] = x.Open / x.Previous_Close - 1
    x["Signal"] = x.Gap.le(THRESHOLD)
    # The causal signal is complete before forward-return columns are created.
    for horizon, offset in HORIZONS.items():
        x[f"Exit_Date_{horizon}D"] = x.Date.shift(-offset)
        x[f"Future_Return_{horizon}D"] = x.Close.shift(-offset) / x.Open - 1
    return x


def validate_ticker(x):
    expected_gap = x.Open.to_numpy()[1:] / x.Close.to_numpy()[:-1] - 1
    assert np.isnan(x.Gap.iloc[0])
    assert np.allclose(x.Gap.iloc[1:], expected_gap, atol=0, rtol=1e-14)
    assert np.array_equal(x.Signal, x.Gap.le(THRESHOLD))
    for i in range(1, len(x) - 4):
        assert x.Previous_Close.iloc[i] == x.Close.iloc[i - 1]
        for horizon, offset in HORIZONS.items():
            assert x[f"Exit_Date_{horizon}D"].iloc[i] == x.Date.iloc[i + offset]
            expected = x.Close.iloc[i + offset] / x.Open.iloc[i] - 1
            assert np.isclose(x[f"Future_Return_{horizon}D"].iloc[i], expected)
    for end in (25, len(x) // 2, len(x) - 5):
        prefix = build_ticker(x.iloc[:end])
        assert np.array_equal(prefix.Signal, x.Signal.iloc[:end])
    cut = len(x) // 2
    changed = x[["Open", "High", "Low", "Close", "Volume", "Date", "Ticker"]].copy()
    changed.loc[cut + 1 :, ["Open", "High", "Low", "Close"]] *= 7
    assert np.array_equal(build_ticker(changed).Signal.iloc[: cut + 1], x.Signal.iloc[: cut + 1])


def metric_rows(x, group, year="ALL"):
    rows = []
    for horizon in HORIZONS:
        returns = x[f"Future_Return_{horizon}D"]
        rows.append(
            {
                "Group": group,
                "Year": year,
                "Horizon": horizon,
                "N": len(x),
                "Mean": returns.mean(),
                "Median": returns.median(),
                "Win_Rate": returns.gt(0).mean(),
            }
        )
    return rows


def proximity(x):
    x = x.sort_values(["Ticker", "Session"])
    gaps = x.groupby("Ticker").Session.diff()
    run_ids = gaps.ne(1).groupby(x.Ticker).cumsum()
    run_sizes = x.groupby(["Ticker", run_ids]).size()
    return {
        "contiguous_stress_phases": int(len(run_sizes)),
        "phases_with_multiple_signals": int(run_sizes.gt(1).sum()),
        "signals_beyond_first_in_phase": int((run_sizes - 1).sum()),
        "max_contiguous_phase": int(run_sizes.max()),
        "previous_signal_1_session_ago": int(gaps.eq(1).sum()),
        "previous_signal_within_3_sessions": int(gaps.le(3).sum()),
        "previous_signal_within_5_sessions": int(gaps.le(5).sum()),
    }


def concentration_tables(signal):
    ticker_rows, year_rows, summary = [], [], {}
    for horizon in HORIZONS:
        col = f"Future_Return_{horizon}D"
        ticker = signal.groupby("Ticker")[col].agg(["size", "mean", "median", "sum"])
        ticker = ticker.sort_values("sum", ascending=False)
        year = signal.groupby("Year")[col].agg(["size", "mean", "median", "sum"])
        year = year.sort_values("sum", ascending=False)
        for name, row in ticker.iterrows():
            ticker_rows.append(
                {"Horizon": horizon, "Ticker": name, "N": int(row["size"]),
                 "Mean": row["mean"], "Median": row["median"], "Contribution_Sum": row["sum"]}
            )
        for name, row in year.iterrows():
            year_rows.append(
                {"Horizon": horizon, "Year": int(name), "N": int(row["size"]),
                 "Mean": row["mean"], "Median": row["median"], "Contribution_Sum": row["sum"]}
            )
        total = signal[col].sum()
        removals = []
        for count in (1, 3, 5):
            removed = list(ticker.index[:count])
            remaining = signal.loc[~signal.Ticker.isin(removed), col]
            removals.append({"count": count, "tickers": removed, "remaining_n": len(remaining),
                             "remaining_mean": float(remaining.mean())})
        top_ticker = str(ticker.index[0])
        top_year = int(year.index[0])
        summary[str(horizon)] = {
            "positive_mean_tickers": int(ticker["mean"].gt(0).sum()),
            "positive_mean_years": int(year["mean"].gt(0).sum()),
            "top_ticker": top_ticker,
            "top_ticker_n": int(ticker.iloc[0]["size"]),
            "top_ticker_contribution": float(ticker.iloc[0]["sum"]),
            "top_ticker_share_of_total": float(ticker.iloc[0]["sum"] / total),
            "top_year": top_year,
            "top_year_n": int(year.iloc[0]["size"]),
            "top_year_contribution": float(year.iloc[0]["sum"]),
            "top_year_share_of_total": float(year.iloc[0]["sum"] / total),
            "mean_without_top_year": float(signal.loc[signal.Year.ne(top_year), col].mean()),
            "remove_top_tickers": removals,
        }
    return ticker_rows, year_rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlc-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("results/gap_down_fade/initial"))
    args = parser.parse_args()

    raw = pd.read_csv(args.ohlc_csv, parse_dates=["Date"])
    required = ["Date", "Ticker", "Open", "High", "Low", "Close"]
    assert set(required).issubset(raw.columns)
    assert not raw.duplicated(["Ticker", "Date"]).any()
    assert raw[required[2:]].notna().all().all()
    assert (raw[required[2:]] > 0).all().all()
    assert raw.High.ge(raw[["Open", "Close", "Low"]].max(axis=1)).all()
    assert raw.Low.le(raw[["Open", "Close", "High"]].min(axis=1)).all()
    calendars = [tuple(z.sort_values("Date").Date) for _, z in raw.groupby("Ticker")]
    assert all(calendar == calendars[0] for calendar in calendars)

    frames = []
    for _, group in raw.groupby("Ticker"):
        x = build_ticker(group)
        validate_ticker(x)
        frames.append(x.iloc[1:-4])  # common universe with all three exits
    data = pd.concat(frames, ignore_index=True)
    assert data[["Gap"] + [f"Future_Return_{h}D" for h in HORIZONS]].notna().all().all()
    data["Year"] = data.Date.dt.year
    signal = data[data.Signal].copy()

    metrics = metric_rows(data, "BASELINE_LONG") + metric_rows(signal, "GAP_DOWN_FADE_LONG")
    counts = []
    for year in sorted(data.Year.unique()):
        metrics += metric_rows(data[data.Year.eq(year)], "BASELINE_LONG", int(year))
        z = signal[signal.Year.eq(year)]
        metrics += metric_rows(z, "GAP_DOWN_FADE_LONG", int(year))
        counts.append(
            {"Year": int(year), "N": len(z), "Tickers": z.Ticker.nunique(), "Dates": z.Date.nunique(),
             "Gap_Mean": z.Gap.mean(), "Gap_Median": z.Gap.median()}
        )

    ticker_rows, year_rows, concentration = concentration_tables(signal)
    summary = {
        "research_status": "EXPLORATORY_POST_HOC_NOT_INDEPENDENT_VALIDATION",
        "origin": "Hypothesis formed after observing rejected Gap Continuation V1 results",
        "threshold": THRESHOLD,
        "direction": "LONG",
        "ohlc_sha256": hashlib.sha256(args.ohlc_csv.read_bytes()).hexdigest(),
        "raw_rows": len(raw),
        "raw_tickers": raw.Ticker.nunique(),
        "raw_period": [str(raw.Date.min().date()), str(raw.Date.max().date())],
        "common_evaluation_rows": len(data),
        "evaluation_period": [str(data.Date.min().date()), str(data.Date.max().date())],
        "signals": len(signal),
        "tickers": int(signal.Ticker.nunique()),
        "dates": int(signal.Date.nunique()),
        "gap_mean": float(signal.Gap.mean()),
        "gap_median": float(signal.Gap.median()),
        "proximity": proximity(signal),
        "concentration": concentration,
        "checks": "gap identity, common calendar, prefix invariance, future mutation, exact t/t+2/t+4 exits passed",
        "execution_limitation": "Open[t] is theoretical and potentially optimistic; future validation requires opening-specific slippage.",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics).to_csv(args.output_dir / "statistics.csv", index=False)
    pd.DataFrame(counts).to_csv(args.output_dir / "annual_counts.csv", index=False)
    pd.DataFrame(ticker_rows).to_csv(args.output_dir / "ticker_concentration.csv", index=False)
    pd.DataFrame(year_rows).to_csv(args.output_dir / "year_concentration.csv", index=False)
    keep = ["Date", "Ticker", "Session", "Open", "Previous_Close", "Gap"]
    keep += [f"Exit_Date_{h}D" for h in HORIZONS] + [f"Future_Return_{h}D" for h in HORIZONS]
    signal[keep].to_csv(args.output_dir / "signals.csv", index=False)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(metrics).query("Year == 'ALL'").to_string(index=False))


if __name__ == "__main__":
    main()
