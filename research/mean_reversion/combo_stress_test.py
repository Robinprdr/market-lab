import pandas as pd
import numpy as np
from itertools import combinations

# ============================================================
# CONFIGURATION
# ============================================================

TRADES_FILE = "results/mean_reversion/trades_autopsy.csv"

TEST_START = "2021-01-01"
TEST_END = "2025-12-20"

DROP_FILTER = -0.04

MIN_TRADES_PER_WINDOW = 10

# Fenêtres walk-forward
WINDOWS = [
    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("2022-01-01", "2025-01-01", "2025-01-01", "2025-12-20"),
]

# Combinaisons que nous voulons stresser
TOP_COMBINATIONS = [
    ("Distance_SMA20", "Distance_SMA50"),
    ("Distance_SMA50", "Drop_ATR_Ratio"),
    ("Return_3D", "Drop_ATR_Ratio"),
    ("Return_3D", "SPY_Return"),
    ("SPY_Return", "SPY_Distance_SMA50"),
]

OUTPUT_FILE = "results/mean_reversion/combo_stress_test.csv"


# ============================================================
# UTILITAIRES
# ============================================================

def find_pnl_column(df):
    """
    Détecte automatiquement la colonne PnL.
    """
    candidates = [
        "PnL_Pct",
        "PnL",
        "Return",
        "Trade_Return",
    ]

    for col in candidates:
        if col in df.columns:
            return col

    raise ValueError(
        "Impossible de trouver la colonne PnL. "
        "Colonnes disponibles : "
        + ", ".join(df.columns)
    )


def prepare_data(df):
    """
    Nettoyage minimal des données.
    """

    df = df.copy()

    df["Date"] = pd.to_datetime(df["Date"])

    # Filtre de base découvert précédemment
    df = df[df["Signal_Drop"] >= DROP_FILTER].copy()

    return df


def get_quartile_edges(train_series):
    """
    Calcule les frontières des quartiles UNIQUEMENT sur le TRAIN.
    """

    values = train_series.dropna()

    if len(values) < 20:
        return None

    q = values.quantile([0.25, 0.50, 0.75]).values

    return q


def assign_quartile(series, edges):
    """
    Attribue Q1/Q2/Q3/Q4 avec des frontières venant du TRAIN.
    """

    if edges is None:
        return pd.Series(index=series.index, dtype="float")

    q1, q2, q3 = edges

    result = pd.Series(index=series.index, dtype="float")

    result[series <= q1] = 1
    result[(series > q1) & (series <= q2)] = 2
    result[(series > q2) & (series <= q3)] = 3
    result[series > q3] = 4

    return result


def get_best_quartile(train, factor, pnl_col):
    """
    Cherche le meilleur quartile du facteur sur TRAIN uniquement.
    """

    edges = get_quartile_edges(train[factor])

    if edges is None:
        return None, None

    train_q = assign_quartile(train[factor], edges)

    temp = train.copy()
    temp["Quartile"] = train_q

    stats = (
        temp.dropna(subset=["Quartile", pnl_col])
        .groupby("Quartile")[pnl_col]
        .agg(["mean", "count"])
    )

    if stats.empty:
        return None, None

    # On exige un minimum de trades pour éviter
    # qu'un quartile avec 2 trades gagne artificiellement.
    stats_valid = stats[stats["count"] >= MIN_TRADES_PER_WINDOW]

    if stats_valid.empty:
        return None, None

    best_q = stats_valid["mean"].idxmax()

    return int(best_q), edges


def select_combo_trades(train, test, factor_a, factor_b, pnl_col):
    """
    Sélectionne les trades TEST correspondant aux meilleurs
    quartiles trouvés sur TRAIN.

    IMPORTANT :
    aucun résultat du TEST n'est utilisé pour choisir les quartiles.
    """

    best_q_a, edges_a = get_best_quartile(
        train,
        factor_a,
        pnl_col
    )

    best_q_b, edges_b = get_best_quartile(
        train,
        factor_b,
        pnl_col
    )

    if best_q_a is None or best_q_b is None:
        return None, None, None, None

    test = test.copy()

    test["Q_A"] = assign_quartile(
        test[factor_a],
        edges_a
    )

    test["Q_B"] = assign_quartile(
        test[factor_b],
        edges_b
    )

    selected = test[
        (test["Q_A"] == best_q_a)
        &
        (test["Q_B"] == best_q_b)
    ].copy()

    return (
        selected,
        best_q_a,
        best_q_b,
        edges_a,
    )


def calculate_stats(pnls):
    """
    Calcule les statistiques principales.
    """

    pnls = pd.Series(pnls).dropna()

    if len(pnls) == 0:
        return {
            "Trades": 0,
            "Win_Rate": np.nan,
            "Avg_PnL": np.nan,
            "Median_PnL": np.nan,
            "Total_PnL": np.nan,
        }

    return {
        "Trades": len(pnls),
        "Win_Rate": (pnls > 0).mean(),
        "Avg_PnL": pnls.mean(),
        "Median_PnL": pnls.median(),
        "Total_PnL": pnls.sum(),
    }


def stress_stats(pnls, remove_fraction):
    """
    Retire les meilleurs X% des trades.

    Exemple :
    remove_fraction = 0.05
    => suppression des meilleurs 5% des trades.

    Le classement est effectué uniquement sur les trades TEST
    sélectionnés par la combinaison.
    """

    pnls = pd.Series(pnls).dropna()

    if len(pnls) == 0:
        return calculate_stats(pnls)

    if remove_fraction <= 0:
        return calculate_stats(pnls)

    n_remove = int(np.floor(len(pnls) * remove_fraction))

    if n_remove <= 0:
        return calculate_stats(pnls)

    # Tri décroissant : meilleurs trades en premier
    sorted_pnls = pnls.sort_values(ascending=False)

    stressed = sorted_pnls.iloc[n_remove:]

    return calculate_stats(stressed)


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("COMBO STRESS TEST")
print("=" * 70)

df = pd.read_csv(TRADES_FILE)

pnl_col = find_pnl_column(df)

print(f"\nColonne PnL détectée : {pnl_col}")

print(f"Trades avant filtre : {len(df)}")

df = prepare_data(df)

print(
    f"Trades après Signal_Drop >= {DROP_FILTER:.2%} : "
    f"{len(df)}"
)

print("\nCombinaisons testées :")

for combo in TOP_COMBINATIONS:
    print(f"  - {combo[0]} + {combo[1]}")


# ============================================================
# WALK-FORWARD + STRESS TEST
# ============================================================

results = []

for window_number, (
    train_start,
    train_end,
    test_start,
    test_end,
) in enumerate(WINDOWS, start=1):

    print("\n" + "=" * 70)
    print(f"WINDOW {window_number}")
    print(
        f"TRAIN : {train_start} -> {train_end}"
    )
    print(
        f"TEST  : {test_start} -> {test_end}"
    )
    print("=" * 70)

    train = df[
        (df["Date"] >= train_start)
        &
        (df["Date"] < train_end)
    ].copy()

    test = df[
        (df["Date"] >= test_start)
        &
        (df["Date"] < test_end)
    ].copy()

    print(
        f"Trades TRAIN : {len(train)} | "
        f"Trades TEST : {len(test)}"
    )

    for factor_a, factor_b in TOP_COMBINATIONS:

        # Vérification des colonnes
        if factor_a not in train.columns:
            print(f"\n⚠️ Colonne absente : {factor_a}")
            continue

        if factor_b not in train.columns:
            print(f"\n⚠️ Colonne absente : {factor_b}")
            continue

        selected, best_q_a, best_q_b, _ = select_combo_trades(
            train,
            test,
            factor_a,
            factor_b,
            pnl_col,
        )

        if selected is None:
            print(
                f"\n{factor_a} + {factor_b} : "
                "impossible de calculer"
            )
            continue

        pnl = selected[pnl_col].dropna()

        if len(pnl) < MIN_TRADES_PER_WINDOW:
            print(
                f"\n{factor_a} + {factor_b} : "
                f"{len(pnl)} trades -> ignoré"
            )
            continue

        print(
            f"\n{factor_a} + {factor_b}"
        )

        print(
            f"  Quartiles TRAIN : "
            f"{factor_a}=Q{best_q_a}, "
            f"{factor_b}=Q{best_q_b}"
        )

        print(
            f"  TEST : {len(pnl)} trades"
        )

        # ----------------------------------------------------
        # STRESS LEVELS
        # ----------------------------------------------------

        stress_levels = [
            0.00,
            0.01,
            0.05,
            0.10,
        ]

        for remove_fraction in stress_levels:

            stats = stress_stats(
                pnl,
                remove_fraction
            )

            result = {
                "Window": window_number,

                "Train_Start": train_start,
                "Train_End": train_end,

                "Test_Start": test_start,
                "Test_End": test_end,

                "Factor_A": factor_a,
                "Factor_B": factor_b,

                "Best_Q_A": best_q_a,
                "Best_Q_B": best_q_b,

                "Remove_Top_Pct": remove_fraction,

                "Trades": stats["Trades"],
                "Win_Rate": stats["Win_Rate"],
                "Avg_PnL": stats["Avg_PnL"],
                "Median_PnL": stats["Median_PnL"],
                "Total_PnL": stats["Total_PnL"],
            }

            results.append(result)

            print(
                f"    - Top {remove_fraction:.0%} retiré : "
                f"{stats['Trades']} trades | "
                f"Win {stats['Win_Rate']:.1%} | "
                f"Avg {stats['Avg_PnL']:.3%} | "
                f"Total {stats['Total_PnL']:.2%}"
            )


# ============================================================
# DATAFRAME RESULTATS
# ============================================================

results_df = pd.DataFrame(results)

if results_df.empty:
    raise ValueError(
        "Aucun résultat disponible. "
        "Vérifie les colonnes et les données."
    )


# ============================================================
# SUMMARY GLOBAL
# ============================================================

summary_rows = []

for (factor_a, factor_b), combo_df in results_df.groupby(
    ["Factor_A", "Factor_B"]
):

    row = {
        "Factor_A": factor_a,
        "Factor_B": factor_b,
    }

    for remove_fraction in [0.00, 0.01, 0.05, 0.10]:

        subset = combo_df[
            combo_df["Remove_Top_Pct"] == remove_fraction
        ].copy()

        if subset.empty:
            continue

        positive_windows = (
            subset["Avg_PnL"] > 0
        ).sum()

        total_windows = len(subset)

        avg_pnl = subset["Avg_PnL"].mean()
        avg_win_rate = subset["Win_Rate"].mean()
        total_trades = subset["Trades"].sum()
        total_pnl = subset["Total_PnL"].sum()

        prefix = f"Remove_{int(remove_fraction * 100)}pct"

        row[f"{prefix}_Positive_Windows"] = positive_windows
        row[f"{prefix}_Total_Windows"] = total_windows

        row[f"{prefix}_Avg_PnL"] = avg_pnl
        row[f"{prefix}_Avg_Win_Rate"] = avg_win_rate

        row[f"{prefix}_Trades"] = total_trades
        row[f"{prefix}_Total_PnL"] = total_pnl

    summary_rows.append(row)


summary_df = pd.DataFrame(summary_rows)


# ============================================================
# AFFICHAGE
# ============================================================

print("\n")
print("=" * 70)
print("RÉSUMÉ DU STRESS TEST")
print("=" * 70)

for _, row in summary_df.iterrows():

    factor_a = row["Factor_A"]
    factor_b = row["Factor_B"]

    print(
        f"\n{factor_a} + {factor_b}"
    )

    for remove_fraction in [0.00, 0.01, 0.05, 0.10]:

        prefix = f"Remove_{int(remove_fraction * 100)}pct"

        positive = row.get(
            f"{prefix}_Positive_Windows",
            np.nan
        )

        total_windows = row.get(
            f"{prefix}_Total_Windows",
            np.nan
        )

        avg_pnl = row.get(
            f"{prefix}_Avg_PnL",
            np.nan
        )

        avg_win = row.get(
            f"{prefix}_Avg_Win_Rate",
            np.nan
        )

        trades = row.get(
            f"{prefix}_Trades",
            np.nan
        )

        total_pnl = row.get(
            f"{prefix}_Total_PnL",
            np.nan
        )

        print(
            f"  Top {remove_fraction:.0%} retiré : "
            f"{int(positive) if not pd.isna(positive) else 0}/"
            f"{int(total_windows) if not pd.isna(total_windows) else 0} "
            f"fenêtres positives | "
            f"Avg {avg_pnl:.3%} | "
            f"Win {avg_win:.1%} | "
            f"Trades {int(trades)} | "
            f"Total {total_pnl:.2%}"
        )


# ============================================================
# EXPORT
# ============================================================

results_df.to_csv(
    OUTPUT_FILE,
    index=False
)

summary_df.to_csv(
    "results/mean_reversion/combo_stress_test_summary.csv",
    index=False
)

print("\n")
print("=" * 70)
print("FICHIERS CRÉÉS")
print("=" * 70)

print(f"✓ {OUTPUT_FILE}")
print("✓ results/mean_reversion/combo_stress_test_summary.csv")

print("\nTerminé.")