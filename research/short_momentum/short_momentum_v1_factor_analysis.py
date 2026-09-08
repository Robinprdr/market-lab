from pathlib import Path
import pandas as pd
import numpy as np

INPUT_FILE = Path("results/short_momentum/short_momentum_v1_research.csv")

HORIZONS = [1, 3, 5, 10]

FACTORS = [
    "Return_1D",
    "Return_3D",
    "Return_5D",
    "Return_10D",
    "Return_20D",
    "ATR_Pct",
    "Volume_Ratio",
    "Negative_Days_5",
    "Negative_Days_10",
    "Consecutive_Down_Days",
    "Return_Consecutive_Down",
    "Momentum_Acceleration_5D",
    "SPY_Return_10D",
]


def analyze_factor(df, factor, future_col):

    data = df[[factor, future_col]].dropna().copy()

    if len(data) < 100:
        return None

    try:
        data["Quantile"] = pd.qcut(
            data[factor],
            5,
            labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
            duplicates="drop"
        )
    except ValueError:
        return None

    grouped = (
        data.groupby("Quantile", observed=False)[future_col]
        .agg(
            Mean="mean",
            Median="median",
            Count="count"
        )
    )

    grouped["WinRate"] = (
        data.groupby("Quantile", observed=False)[future_col]
        .apply(lambda x: (x > 0).mean())
    )

    return grouped


def main():

    print("=" * 80)
    print("SHORT MOMENTUM V1 — FACTOR ANALYSIS")
    print("=" * 80)

    df = pd.read_csv(INPUT_FILE)

    print(f"\nDataset : {len(df):,} lignes")
    print(f"Actions : {df['Ticker'].nunique()}")

    for horizon in HORIZONS:

        future_col = f"Future_Return_{horizon}D"

        print("\n")
        print("=" * 80)
        print(f"HORIZON : {horizon} JOUR(S)")
        print("=" * 80)

        for factor in FACTORS:

            result = analyze_factor(
                df,
                factor,
                future_col
            )

            if result is None:
                continue

            print(f"\n--- {factor} ---")

            for quantile, row in result.iterrows():

                print(
                    f"{quantile}: "
                    f"mean {row['Mean']:+.3%} | "
                    f"median {row['Median']:+.3%} | "
                    f"WR {row['WinRate']:.1%} | "
                    f"n={int(row['Count']):,}"
                )

            try:
                spread = (
                    result.loc["Q5", "Mean"]
                    - result.loc["Q1", "Mean"]
                )

                print(
                    f"SPREAD Q5-Q1 : {spread:+.3%}"
                )

            except KeyError:
                pass

    print("\n")
    print("=" * 80)
    print("FIN DE L'ANALYSE")
    print("=" * 80)


if __name__ == "__main__":
    main()
