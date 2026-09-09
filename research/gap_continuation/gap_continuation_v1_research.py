"""Fixed Gap Continuation factor study with a 2% threshold.

A: Gap[t] = Open[t] / Close[t-1] - 1 >= 0.02 (LONG continuation).
B: Gap[t] <= -0.02 (SHORT continuation).
Signal and theoretical entry are both at Open[t]. Returns describe the stock:
1D Close[t]/Open[t]-1, 3D Close[t+2]/Open[t]-1,
5D Close[t+4]/Open[t]-1. No costs, filters, sizing or optimization.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HORIZONS = {1: 0, 3: 2, 5: 4}
THRESHOLD = 0.02


def build_ticker(frame):
    x = frame.sort_values("Date").reset_index(drop=True).copy()
    x["Session"] = np.arange(len(x))
    x["Previous_Close"] = x.Close.shift(1)
    x["Gap"] = x.Open / x.Previous_Close - 1
    x["A"] = x.Gap.ge(THRESHOLD)
    x["B"] = x.Gap.le(-THRESHOLD)

    # Signal fields are complete before any forward-return field is added.
    for horizon, offset in HORIZONS.items():
        x[f"Exit_Date_{horizon}D"] = x.Date.shift(-offset)
        x[f"Future_Return_{horizon}D"] = x.Close.shift(-offset) / x.Open - 1
    return x


def validate_ticker(x):
    expected_gap = x.Open.to_numpy()[1:] / x.Close.to_numpy()[:-1] - 1
    assert np.isnan(x.Gap.iloc[0])
    assert np.allclose(x.Gap.iloc[1:], expected_gap, atol=0, rtol=1e-14)
    assert np.array_equal(x.A, x.Gap.ge(THRESHOLD))
    assert np.array_equal(x.B, x.Gap.le(-THRESHOLD))
    assert not (x.A & x.B).any()

    for i in range(1, len(x) - 4):
        assert x.Previous_Close.iloc[i] == x.Close.iloc[i - 1]
        for horizon, offset in HORIZONS.items():
            assert x[f"Exit_Date_{horizon}D"].iloc[i] == x.Date.iloc[i + offset]
            expected = x.Close.iloc[i + offset] / x.Open.iloc[i] - 1
            assert np.isclose(x[f"Future_Return_{horizon}D"].iloc[i], expected)

    # Prefix invariance and future mutation prove signal causality.
    for end in (25, len(x) // 2, len(x) - 5):
        prefix = build_ticker(x.iloc[:end])
        assert np.array_equal(prefix[["A", "B"]], x[["A", "B"]].iloc[:end])
    cut = len(x) // 2
    changed = x[["Open", "High", "Low", "Close", "Volume", "Date", "Ticker"]].copy()
    changed.loc[cut + 1 :, ["Open", "High", "Low", "Close"]] *= 7
    rebuilt = build_ticker(changed)
    assert np.array_equal(rebuilt[["A", "B"]].iloc[: cut + 1], x[["A", "B"]].iloc[: cut + 1])


def metric_rows(x, group, direction, year="ALL"):
    rows = []
    for horizon in HORIZONS:
        returns = x[f"Future_Return_{horizon}D"]
        favorable = returns.gt(0) if direction == "LONG" else returns.lt(0)
        rows.append(
            {
                "Group": group,
                "Direction": direction,
                "Year": year,
                "Horizon": horizon,
                "N": len(x),
                "Action_Mean": returns.mean(),
                "Action_Median": returns.median(),
                "Directional_Win_Rate": favorable.mean(),
                "Directional_Mean": returns.mean() if direction == "LONG" else -returns.mean(),
            }
        )
    return rows


def proximity_summary(x):
    x = x.sort_values(["Ticker", "Session"])
    gaps = x.groupby("Ticker").Session.diff()
    contiguous_starts = gaps.ne(1)
    run_ids = contiguous_starts.groupby(x.Ticker).cumsum()
    run_sizes = x.groupby(["Ticker", run_ids]).size()
    return {
        "contiguous_runs": int(len(run_sizes)),
        "runs_with_multiple_gaps": int(run_sizes.gt(1).sum()),
        "gaps_beyond_first_in_contiguous_run": int((run_sizes - 1).sum()),
        "max_contiguous_run": int(run_sizes.max()),
        "previous_same_group_gap_1_session": int(gaps.eq(1).sum()),
        "previous_same_group_gap_within_3_sessions": int(gaps.le(3).sum()),
        "previous_same_group_gap_within_5_sessions": int(gaps.le(5).sum()),
    }


def concentration_rows(x, group, direction):
    rows = []
    for horizon in HORIZONS:
        col = f"Future_Return_{horizon}D"
        for ticker, z in x.groupby("Ticker"):
            action = z[col]
            directional = action if direction == "LONG" else -action
            rows.append(
                {
                    "Group": group,
                    "Direction": direction,
                    "Horizon": horizon,
                    "Ticker": ticker,
                    "N": len(z),
                    "Action_Mean": action.mean(),
                    "Directional_Mean": directional.mean(),
                    "Directional_Contribution_Sum": directional.sum(),
                }
            )
    return rows


def concentration_summary(x, group, direction):
    answer = {}
    for horizon in HORIZONS:
        col = f"Future_Return_{horizon}D"
        directional = x[col] if direction == "LONG" else -x[col]
        ticker_sum = directional.groupby(x.Ticker).sum().sort_values(ascending=False)
        year_sum = directional.groupby(x.Year).sum().sort_values(ascending=False)
        top_ticker = str(ticker_sum.index[0])
        top_year = int(year_sum.index[0])
        overall = float(directional.sum())
        without_top_ticker = directional[x.Ticker.ne(top_ticker)].mean()
        without_top_year = directional[x.Year.ne(top_year)].mean()
        answer[str(horizon)] = {
            "total_directional_contribution_equal_one_per_signal": overall,
            "top_ticker": top_ticker,
            "top_ticker_contribution": float(ticker_sum.iloc[0]),
            "top_ticker_share_of_total": float(ticker_sum.iloc[0] / overall) if overall != 0 else None,
            "directional_mean_without_top_ticker": float(without_top_ticker),
            "top_year": top_year,
            "top_year_contribution": float(year_sum.iloc[0]),
            "top_year_share_of_total": float(year_sum.iloc[0] / overall) if overall != 0 else None,
            "directional_mean_without_top_year": float(without_top_year),
        }
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlc-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("results/gap_continuation/initial"))
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
        # Require previous close and all three exits for one common universe.
        frames.append(x.iloc[1:-4])
    data = pd.concat(frames, ignore_index=True)
    assert data[["Gap"] + [f"Future_Return_{h}D" for h in HORIZONS]].notna().all().all()
    data["Year"] = data.Date.dt.year

    metrics = []
    counts = []
    concentration = []
    groups = {
        "BASELINE_LONG": (data, "LONG"),
        "BASELINE_SHORT": (data, "SHORT"),
        "A_GAP_UP": (data[data.A], "LONG"),
        "B_GAP_DOWN": (data[data.B], "SHORT"),
    }
    for name, (x, direction) in groups.items():
        metrics += metric_rows(x, name, direction)
        for year in sorted(data.Year.unique()):
            z = x[x.Year.eq(year)]
            metrics += metric_rows(z, name, direction, int(year))
            counts.append(
                {
                    "Group": name,
                    "Direction": direction,
                    "Year": int(year),
                    "N": len(z),
                    "Tickers": z.Ticker.nunique(),
                    "Dates": z.Date.nunique(),
                    "Gap_Mean": z.Gap.mean(),
                    "Gap_Median": z.Gap.median(),
                }
            )
        if name.startswith(("A_", "B_")):
            concentration += concentration_rows(x, name, direction)

    summary = {
        "ohlc_sha256": hashlib.sha256(args.ohlc_csv.read_bytes()).hexdigest(),
        "raw_rows": len(raw),
        "raw_tickers": raw.Ticker.nunique(),
        "raw_period": [str(raw.Date.min().date()), str(raw.Date.max().date())],
        "common_evaluation_rows": len(data),
        "evaluation_period": [str(data.Date.min().date()), str(data.Date.max().date())],
        "threshold": THRESHOLD,
        "groups": {},
        "checks": "gap identity, common calendar, prefix invariance, future mutation, exact t/t+2/t+4 exits passed",
        "execution_limitation": "Open[t] is theoretical and may be optimistic; future validation requires realistic opening slippage.",
    }
    for name, (x, direction) in groups.items():
        if name.startswith("BASELINE"):
            continue
        summary["groups"][name] = {
            "direction": direction,
            "observations": len(x),
            "tickers": int(x.Ticker.nunique()),
            "dates": int(x.Date.nunique()),
            "gap_mean": float(x.Gap.mean()),
            "gap_median": float(x.Gap.median()),
            "proximity": proximity_summary(x),
            "concentration": concentration_summary(x, name, direction),
        }
    summary["same_day_A_B_overlap"] = int((data.A & data.B).sum())

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(metrics).to_csv(args.output_dir / "statistics.csv", index=False)
    pd.DataFrame(counts).to_csv(args.output_dir / "annual_counts.csv", index=False)
    pd.DataFrame(concentration).to_csv(args.output_dir / "ticker_concentration.csv", index=False)
    keep = ["Date", "Ticker", "Session", "Open", "Previous_Close", "Gap", "A", "B"]
    keep += [f"Exit_Date_{h}D" for h in HORIZONS] + [f"Future_Return_{h}D" for h in HORIZONS]
    data.loc[data.A | data.B, keep].to_csv(args.output_dir / "observations.csv", index=False)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(metrics).query("Year == 'ALL'").to_string(index=False))


if __name__ == "__main__":
    main()
