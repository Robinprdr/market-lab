import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")
OUTPUT_FILE = Path("results/momentum/momentum_v1_ranking_walk_forward.csv")

HORIZONS = [1, 3, 5]

WINDOWS = [
    ("W1", "2018-10-16", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("W2", "2019-01-02", "2022-12-30", "2023-01-01", "2023-12-31"),
    ("W3", "2020-01-02", "2023-12-29", "2024-01-01", "2024-12-31"),
    ("W4", "2021-01-04", "2024-12-31", "2025-01-01", "2025-12-31"),
]


def empirical_percentile(values, train_values):
    """
    Percentile of each value relative to TRAIN only.
    No information from the test period is used.
    """
    train_values = np.asarray(train_values, dtype=float)
    values = np.asarray(values, dtype=float)

    train_values = train_values[np.isfinite(train_values)]
    train_values.sort()

    if len(train_values) == 0:
        return np.full(len(values), np.nan)

    positions = np.searchsorted(train_values, values, side="right")
    return positions / len(train_values)


def evaluate(df, name, baseline_returns):
    rows = []

    for horizon in HORIZONS:
        col = f"Future_Return_{horizon}D"

        data = df[[col]].dropna()

        if len(data) == 0:
            continue

        avg_return = data[col].mean()
        win_rate = (data[col] > 0).mean()

        rows.append({
            "Signal": name,
            "Horizon": horizon,
            "Observations": len(data),
            "Coverage_pct": len(data) / len(df) * 100,
            "Avg_Return_pct": avg_return * 100,
            "Win_Rate_pct": win_rate * 100,
            "Excess_vs_Baseline_pp": (
                avg_return - baseline_returns[horizon]
            ) * 100,
        })

    return rows


print("=" * 90)
print("MOMENTUM V1 - RANKING WALK-FORWARD")
print("=" * 90)

df = pd.read_csv(INPUT_FILE, parse_dates=["Date"])

print(f"Dataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")
print(
    f"Période : "
    f"{df['Date'].min().date()} → {df['Date'].max().date()}"
)

all_results = []

for window_name, train_start, train_end, test_start, test_end in WINDOWS:

    train = df[
        (df["Date"] >= train_start)
        & (df["Date"] <= train_end)
    ].copy()

    test = df[
        (df["Date"] >= test_start)
        & (df["Date"] <= test_end)
    ].copy()

    required = [
        "ATR_Pct",
        "Return_10D",
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
    ]

    train = train.dropna(subset=["ATR_Pct", "Return_10D"])
    test = test.dropna(subset=["ATR_Pct", "Return_10D"])

    print()
    print("-" * 90)
    print(
        f"{window_name} | "
        f"TRAIN {train_start} → {train_end} | "
        f"TEST {test_start} → {test_end}"
    )
    print("-" * 90)

    # ---------------------------------------------------------
    # 1. SEUILS CALCULÉS UNIQUEMENT SUR LE TRAIN
    # ---------------------------------------------------------

    atr_q80 = train["ATR_Pct"].quantile(0.80)
    ret10_q80 = train["Return_10D"].quantile(0.80)

    # ---------------------------------------------------------
    # 2. PERCENTILES TRAIN
    # ---------------------------------------------------------

    atr_train_pct = train["ATR_Pct"].rank(pct=True)
    ret10_train_pct = train["Return_10D"].rank(pct=True)

    train_score = (
        atr_train_pct + ret10_train_pct
    ) / 2

    score_q80 = train_score.quantile(0.80)
    score_q90 = train_score.quantile(0.90)
    score_q95 = train_score.quantile(0.95)

    # ---------------------------------------------------------
    # 3. PERCENTILES TEST RELATIFS AU TRAIN
    # ---------------------------------------------------------

    test["ATR_Pctile"] = empirical_percentile(
        test["ATR_Pct"],
        train["ATR_Pct"]
    )

    test["Return10_Pctile"] = empirical_percentile(
        test["Return_10D"],
        train["Return_10D"]
    )

    test["Research_Score"] = (
        test["ATR_Pctile"]
        + test["Return10_Pctile"]
    ) / 2

    # ---------------------------------------------------------
    # 4. SIGNALS
    # ---------------------------------------------------------

    test["ATR_Q80"] = test["ATR_Pct"] >= atr_q80

    test["COMBO_Q80"] = (
        (test["ATR_Pct"] >= atr_q80)
        & (test["Return_10D"] >= ret10_q80)
    )

    test["SCORE_TOP20"] = (
        test["Research_Score"] >= score_q80
    )

    test["SCORE_TOP10"] = (
        test["Research_Score"] >= score_q90
    )

    test["SCORE_TOP5"] = (
        test["Research_Score"] >= score_q95
    )

    # ---------------------------------------------------------
    # 5. BASELINE TEST
    # ---------------------------------------------------------

    baseline_returns = {}

    for horizon in HORIZONS:
        col = f"Future_Return_{horizon}D"
        baseline_returns[horizon] = test[col].dropna().mean()

    # ---------------------------------------------------------
    # 6. EVALUATION
    # ---------------------------------------------------------

    signals = {
        "ATR_Q80": test[test["ATR_Q80"]].copy(),
        "COMBO_Q80": test[test["COMBO_Q80"]].copy(),
        "SCORE_TOP20": test[test["SCORE_TOP20"]].copy(),
        "SCORE_TOP10": test[test["SCORE_TOP10"]].copy(),
        "SCORE_TOP5": test[test["SCORE_TOP5"]].copy(),
    }

    print(
        f"Train thresholds:"
        f"\n  ATR Q80     = {atr_q80:.6f}"
        f"\n  Return10 Q80= {ret10_q80:.6f}"
        f"\n  Score Q80   = {score_q80:.4f}"
        f"\n  Score Q90   = {score_q90:.4f}"
        f"\n  Score Q95   = {score_q95:.4f}"
    )

    print()

    for signal_name, signal_df in signals.items():

        print(
            f"{signal_name:<14} "
            f"{len(signal_df):>6,} obs "
            f"({len(signal_df) / len(test) * 100:>5.1f}%)"
        )

        for horizon in HORIZONS:

            col = f"Future_Return_{horizon}D"

            values = signal_df[col].dropna()

            if len(values) == 0:
                continue

            avg_return = values.mean()
            win_rate = (values > 0).mean()

            excess = (
                avg_return
                - baseline_returns[horizon]
            )

            print(
                f"  {horizon}D : "
                f"avg {avg_return * 100:+.3f}% | "
                f"WR {win_rate * 100:.1f}% | "
                f"excess {excess * 100:+.3f}pp"
            )

            all_results.append({
                "Window": window_name,
                "Train_Start": train_start,
                "Train_End": train_end,
                "Test_Start": test_start,
                "Test_End": test_end,
                "Signal": signal_name,
                "Horizon": horizon,
                "Observations": len(values),
                "Coverage_pct": len(signal_df) / len(test) * 100,
                "Avg_Return_pct": avg_return * 100,
                "Win_Rate_pct": win_rate * 100,
                "Excess_vs_Baseline_pp": excess * 100,
                "ATR_Q80": atr_q80,
                "Return10_Q80": ret10_q80,
                "Score_Q80": score_q80,
                "Score_Q90": score_q90,
                "Score_Q95": score_q95,
            })


# -------------------------------------------------------------
# 7. SUMMARY WALK-FORWARD
# -------------------------------------------------------------

results = pd.DataFrame(all_results)

print()
print("=" * 90)
print("SUMMARY WALK-FORWARD")
print("=" * 90)

for signal in [
    "ATR_Q80",
    "COMBO_Q80",
    "SCORE_TOP20",
    "SCORE_TOP10",
    "SCORE_TOP5",
]:

    print()
    print(f"### {signal}")

    subset = results[
        results["Signal"] == signal
    ]

    for horizon in HORIZONS:

        h = subset[
            subset["Horizon"] == horizon
        ]

        if len(h) == 0:
            continue

        positive_windows = (
            h["Excess_vs_Baseline_pp"] > 0
        ).sum()

        avg_excess = (
            h["Excess_vs_Baseline_pp"].mean()
        )

        avg_return = (
            h["Avg_Return_pct"].mean()
        )

        avg_wr = (
            h["Win_Rate_pct"].mean()
        )

        print(
            f"{horizon}D | "
            f"positive {positive_windows}/{len(h)} | "
            f"avg return {avg_return:+.3f}% | "
            f"avg WR {avg_wr:.1f}% | "
            f"avg excess {avg_excess:+.3f}pp"
        )


# -------------------------------------------------------------
# 8. SAUVEGARDE
# -------------------------------------------------------------

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

results.to_csv(
    OUTPUT_FILE,
    index=False
)

print()
print("=" * 90)
print(f"Résultats sauvegardés dans : {OUTPUT_FILE}")
print("=" * 90)
