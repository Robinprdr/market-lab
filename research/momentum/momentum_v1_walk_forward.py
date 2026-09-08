import pandas as pd
import numpy as np
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")
OUTPUT_FILE = Path("results/momentum/momentum_v1_walk_forward_results.csv")

TRAIN_YEARS = 4

WINDOWS = [
    ("W1", "2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("W2", "2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("W3", "2020-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("W4", "2021-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
]

HORIZONS = [1, 3, 5, 10]

Q = 0.80


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("MOMENTUM V1 - WALK FORWARD VALIDATION")
print("=" * 70)

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Fichier introuvable : {INPUT_FILE}"
    )

df = pd.read_csv(INPUT_FILE)

df["Date"] = pd.to_datetime(df["Date"])

print(f"\nDataset chargé : {len(df):,} lignes")
print(f"Date min       : {df['Date'].min().date()}")
print(f"Date max       : {df['Date'].max().date()}")
print(f"Actions        : {df['Ticker'].nunique()}")


# ============================================================
# COLONNES FUTURES
# ============================================================

future_columns = {
    1: "Future_Return_1D",
    3: "Future_Return_3D",
    5: "Future_Return_5D",
    10: "Future_Return_10D",
}


# ============================================================
# FONCTION DE STATISTIQUES
# ============================================================

def calculate_stats(data, horizon):
    """
    Calcule les statistiques principales d'un groupe de signaux.
    """

    column = future_columns[horizon]

    values = pd.to_numeric(
        data[column],
        errors="coerce"
    ).dropna()

    if len(values) == 0:
        return {
            "N": 0,
            "Selection_pct": np.nan,
            "Mean": np.nan,
            "Median": np.nan,
            "Win_Rate": np.nan,
        }

    return {
        "N": len(values),
        "Selection_pct": np.nan,
        "Mean": values.mean(),
        "Median": values.median(),
        "Win_Rate": (values > 0).mean(),
    }


# ============================================================
# WALK FORWARD
# ============================================================

all_results = []


for window_name, train_start, train_end, test_start, test_end in WINDOWS:

    print("\n" + "=" * 70)
    print(window_name)
    print("=" * 70)

    train = df[
        (df["Date"] >= train_start)
        & (df["Date"] <= train_end)
    ].copy()

    test = df[
        (df["Date"] >= test_start)
        & (df["Date"] <= test_end)
    ].copy()

    print(
        f"TRAIN : {train['Date'].min().date()} "
        f"-> {train['Date'].max().date()} "
        f"({len(train):,} lignes)"
    )

    print(
        f"TEST  : {test['Date'].min().date()} "
        f"-> {test['Date'].max().date()} "
        f"({len(test):,} lignes)"
    )

    # --------------------------------------------------------
    # SEUILS CALCULÉS UNIQUEMENT SUR LE TRAIN
    # --------------------------------------------------------

    atr_threshold = train["ATR_Pct"].quantile(Q)
    return10_threshold = train["Return_10D"].quantile(Q)

    print("\nSeuils calculés sur TRAIN :")
    print(f"ATR_Pct Q80    : {atr_threshold:.6f}")
    print(f"Return_10D Q80 : {return10_threshold:.6f}")

    # --------------------------------------------------------
    # CONDITIONS
    # --------------------------------------------------------

    conditions = {
        "BASELINE": pd.Series(
            True,
            index=test.index
        ),

        "ATR_Q80": (
            test["ATR_Pct"] >= atr_threshold
        ),

        "RETURN10_Q80": (
            test["Return_10D"] >= return10_threshold
        ),

        "ATR_RETURN10_Q80": (
            (test["ATR_Pct"] >= atr_threshold)
            &
            (test["Return_10D"] >= return10_threshold)
        ),
    }

    # --------------------------------------------------------
    # STATISTIQUES
    # --------------------------------------------------------

    baseline_means = {}

    for strategy_name, condition in conditions.items():

        selected = test[condition].copy()

        selection_pct = (
            len(selected) / len(test) * 100
            if len(test) > 0
            else np.nan
        )

        print(
            f"\n{strategy_name}"
            f" | sélection : {selection_pct:.2f}%"
            f" | N : {len(selected):,}"
        )

        for horizon in HORIZONS:

            stats = calculate_stats(
                selected,
                horizon
            )

            stats["Selection_pct"] = selection_pct

            mean_return = stats["Mean"]

            # ------------------------------------------------
            # BASELINE
            # ------------------------------------------------

            if strategy_name == "BASELINE":
                baseline_means[horizon] = mean_return

            # ------------------------------------------------
            # EXCESS VS BASELINE
            # ------------------------------------------------

            excess = (
                mean_return - baseline_means[horizon]
                if horizon in baseline_means
                and pd.notna(mean_return)
                and pd.notna(baseline_means[horizon])
                else np.nan
            )

            print(
                f"  {horizon:>2}D | "
                f"N={stats['N']:>5} | "
                f"Mean={stats['Mean'] * 100:>7.3f}% | "
                f"Median={stats['Median'] * 100:>7.3f}% | "
                f"WR={stats['Win_Rate'] * 100:>6.1f}%"
                + (
                    f" | Excess={excess * 100:+.3f}pp"
                    if pd.notna(excess)
                    else ""
                )
            )

            all_results.append({
                "Window": window_name,
                "Train_Start": train_start,
                "Train_End": train_end,
                "Test_Start": test_start,
                "Test_End": test_end,

                "Strategy": strategy_name,

                "Horizon_Days": horizon,

                "N": stats["N"],
                "Selection_pct": stats["Selection_pct"],

                "Mean_Return": stats["Mean"],
                "Median_Return": stats["Median"],
                "Win_Rate": stats["Win_Rate"],

                "Baseline_Mean_Return": baseline_means.get(
                    horizon,
                    np.nan
                ),

                "Excess_vs_Baseline": excess,

                "ATR_Q80_Train": atr_threshold,
                "Return10_Q80_Train": return10_threshold,
            })


# ============================================================
# DATAFRAME FINAL
# ============================================================

results = pd.DataFrame(all_results)

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

results.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SYNTHÈSE
# ============================================================

print("\n" + "=" * 70)
print("SYNTHÈSE WALK-FORWARD")
print("=" * 70)

for strategy_name in [
    "ATR_Q80",
    "RETURN10_Q80",
    "ATR_RETURN10_Q80",
]:

    print(f"\n### {strategy_name}")

    strategy_results = results[
        results["Strategy"] == strategy_name
    ]

    for horizon in HORIZONS:

        subset = strategy_results[
            strategy_results["Horizon_Days"] == horizon
        ]

        positive_windows = (
            subset["Excess_vs_Baseline"] > 0
        ).sum()

        total_windows = len(subset)

        avg_excess = subset[
            "Excess_vs_Baseline"
        ].mean()

        median_excess = subset[
            "Excess_vs_Baseline"
        ].median()

        print(
            f"{horizon:>2}D | "
            f"fenêtres positives "
            f"{positive_windows}/{total_windows} | "
            f"excess moyen "
            f"{avg_excess * 100:+.3f}pp | "
            f"médiane "
            f"{median_excess * 100:+.3f}pp"
        )


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 70)
print("TERMINÉ")
print("=" * 70)

print(f"\nRésultats sauvegardés dans :")
print(OUTPUT_FILE)