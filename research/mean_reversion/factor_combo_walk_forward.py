import pandas as pd
import numpy as np
from itertools import combinations


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "results/mean_reversion/trades_autopsy.csv"

DROP_THRESHOLD = -0.04

WINDOWS = [
    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("2022-01-01", "2025-01-01", "2025-01-01", "2025-12-20"),
]


# ============================================================
# FACTEURS CANDIDATS
# ============================================================

FACTORS = [
    "Distance_SMA20",
    "Distance_SMA50",
    "Return_3D",
    "SPY_Return",
    "Drop_ATR_Ratio",
    "SPY_Distance_SMA50",
]


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(INPUT_FILE)

df["Date"] = pd.to_datetime(df["Date"])


# ============================================================
# DETECTION AUTOMATIQUE DE LA COLONNE PNL
# ============================================================

possible_pnl_columns = [
    "PnL_Pct",
    "PnL"
    "PnL_%",
    "PnL_Percent",
    "PnL_pct",
    "Return",
    "Trade_Return",
]

PNL_COLUMN = None

for column in possible_pnl_columns:
    if column in df.columns:
        PNL_COLUMN = column
        break

if PNL_COLUMN is None:
    print("\nERREUR : impossible de trouver la colonne PnL.")
    print("\nColonnes disponibles dans results/mean_reversion/trades_autopsy.csv :")
    for column in df.columns:
        print(f" - {column}")

    raise SystemExit


print("=" * 100)
print("FACTOR COMBINATION WALK-FORWARD")
print("=" * 100)

print(f"Colonne PnL détectée : {PNL_COLUMN}")

print(f"\nTrades disponibles avant filtre : {len(df)}")

df = df[
    df["Signal_Drop"] >= DROP_THRESHOLD
].copy()

print(
    f"Trades disponibles après filtre "
    f"Signal_Drop >= {DROP_THRESHOLD:.0%} : {len(df)}"
)

print("\nFacteurs étudiés :")

for factor in FACTORS:
    print(f" - {factor}")


# ============================================================
# VERIFICATION DES COLONNES
# ============================================================

missing_factors = [
    factor for factor in FACTORS
    if factor not in df.columns
]

if missing_factors:

    print("\nERREUR : facteurs absents du CSV :")

    for factor in missing_factors:
        print(f" - {factor}")

    print("\nColonnes disponibles :")

    for column in df.columns:
        print(f" - {column}")

    raise SystemExit


# ============================================================
# FONCTION : MEILLEUR QUARTILE SUR TRAIN
# ============================================================

def get_best_quartile(train_df, factor):

    data = train_df[
        [factor, PNL_COLUMN]
    ].dropna().copy()

    if len(data) < 20:
        return None

    try:

        data["Quartile"] = pd.qcut(
            data[factor],
            4,
            labels=["Q1", "Q2", "Q3", "Q4"],
            duplicates="drop"
        )

    except Exception:

        return None

    stats = (
        data.groupby(
            "Quartile",
            observed=False
        )[PNL_COLUMN]
        .agg(["mean", "count"])
        .dropna()
    )

    if len(stats) < 4:
        return None

    stats = stats[
        stats["count"] >= 20
    ]

    if len(stats) == 0:
        return None

    best_quartile = stats["mean"].idxmax()

    return {
        "quartile": best_quartile,
        "train_avg": stats.loc[
            best_quartile,
            "mean"
        ],
        "train_count": int(
            stats.loc[
                best_quartile,
                "count"
            ]
        )
    }


# ============================================================
# FONCTION : APPLIQUER LES QUARTILES TRAIN AU TEST
# ============================================================

def apply_train_quartile(
    train_df,
    test_df,
    factor,
    best_info
):

    train_values = train_df[
        factor
    ].dropna()

    if len(train_values) < 20:
        return None

    try:

        _, bins = pd.qcut(
            train_values,
            4,
            retbins=True,
            duplicates="drop"
        )

    except Exception:

        return None

    bins = np.asarray(bins)

    if len(bins) != 5:
        return None

    bins[0] = -np.inf
    bins[-1] = np.inf

    test_copy = test_df.copy()

    test_copy["Quartile"] = pd.cut(
        test_copy[factor],
        bins=bins,
        labels=[
            "Q1",
            "Q2",
            "Q3",
            "Q4"
        ],
        include_lowest=True
    )

    selected = test_copy[
        test_copy["Quartile"]
        == best_info["quartile"]
    ].copy()

    return selected


# ============================================================
# COMBINAISONS DE 2 FACTEURS
# ============================================================

FACTOR_COMBINATIONS = list(
    combinations(
        FACTORS,
        2
    )
)


# ============================================================
# ANALYSE WALK-FORWARD
# ============================================================

all_results = []


for window_id, (
    train_start,
    train_end,
    test_start,
    test_end
) in enumerate(WINDOWS, 1):

    print("\n")
    print("=" * 100)
    print(f"WINDOW {window_id}")
    print(
        f"TRAIN : {train_start} → {train_end}"
    )
    print(
        f"TEST  : {test_start} → {test_end}"
    )
    print("=" * 100)

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
        f"Trades TRAIN : {len(train)}"
    )

    print(
        f"Trades TEST  : {len(test)}"
    )

    if len(train) == 0 or len(test) == 0:
        continue


    # --------------------------------------------------------
    # MEILLEUR QUARTILE DE CHAQUE FACTEUR
    # UNIQUEMENT SUR TRAIN
    # --------------------------------------------------------

    factor_infos = {}

    for factor in FACTORS:

        info = get_best_quartile(
            train,
            factor
        )

        if info is not None:

            factor_infos[
                factor
            ] = info


    # --------------------------------------------------------
    # TEST DES COMBINAISONS
    # --------------------------------------------------------

    for factor_a, factor_b in FACTOR_COMBINATIONS:

        if factor_a not in factor_infos:
            continue

        if factor_b not in factor_infos:
            continue


        info_a = factor_infos[
            factor_a
        ]

        info_b = factor_infos[
            factor_b
        ]


        selected_test_a = apply_train_quartile(
            train,
            test,
            factor_a,
            info_a
        )

        selected_test_b = apply_train_quartile(
            train,
            test,
            factor_b,
            info_b
        )


        if (
            selected_test_a is None
            or selected_test_b is None
        ):
            continue


        # ----------------------------------------------------
        # INTERSECTION
        # ----------------------------------------------------

        common_index = (
            selected_test_a.index
            .intersection(
                selected_test_b.index
            )
        )


        combo_test = test.loc[
            common_index
        ].copy()


        # ----------------------------------------------------
        # MINIMUM DE TRADES
        # ----------------------------------------------------

        n = len(combo_test)

        if n < 10:
            continue


        # ----------------------------------------------------
        # STATISTIQUES
        # ----------------------------------------------------

        avg_pnl = combo_test[
            PNL_COLUMN
        ].mean()

        win_rate = (
            combo_test[
                PNL_COLUMN
            ] > 0
        ).mean()

        total_pnl = combo_test[
            PNL_COLUMN
        ].sum()


        all_results.append({

            "Window": window_id,

            "Train_Start": train_start,
            "Train_End": train_end,

            "Test_Start": test_start,
            "Test_End": test_end,

            "Factor_A": factor_a,
            "Factor_B": factor_b,

            "Train_Q_A": info_a[
                "quartile"
            ],

            "Train_Q_B": info_b[
                "quartile"
            ],

            "Train_Avg_A": info_a[
                "train_avg"
            ],

            "Train_Avg_B": info_b[
                "train_avg"
            ],

            "Test_Trades": n,

            "Test_Win_Rate": win_rate,

            "Test_Avg_PnL": avg_pnl,

            "Test_Sum_PnL": total_pnl
        })


# ============================================================
# RESULTATS
# ============================================================

results = pd.DataFrame(
    all_results
)


if results.empty:

    print("\nAucun résultat exploitable.")

    raise SystemExit


# ============================================================
# SUMMARY
# ============================================================

summary_rows = []


for (
    factor_a,
    factor_b
), group in results.groupby(
    [
        "Factor_A",
        "Factor_B"
    ]
):

    positive_windows = (
        group[
            "Test_Avg_PnL"
        ] > 0
    ).sum()

    total_windows = len(
        group
    )


    summary_rows.append({

        "Factor_A": factor_a,

        "Factor_B": factor_b,

        "Windows": total_windows,

        "Positive_Windows":
            positive_windows,

        "Positive_%":
            positive_windows
            / total_windows,

        "Average_Test_PnL":
            group[
                "Test_Avg_PnL"
            ].mean(),

        "Median_Test_PnL":
            group[
                "Test_Avg_PnL"
            ].median(),

        "Average_Win_Rate":
            group[
                "Test_Win_Rate"
            ].mean(),

        "Total_Test_PnL":
            group[
                "Test_Sum_PnL"
            ].sum(),

        "Total_Test_Trades":
            group[
                "Test_Trades"
            ].sum()
    })


summary = pd.DataFrame(
    summary_rows
)


summary = summary.sort_values(
    [
        "Positive_Windows",
        "Average_Test_PnL"
    ],
    ascending=False
)


# ============================================================
# EXPORT
# ============================================================

results.to_csv(
    "results/mean_reversion/factor_combo_walk_forward_results.csv",
    index=False
)

summary.to_csv(
    "results/mean_reversion/factor_combo_walk_forward_summary.csv",
    index=False
)


# ============================================================
# AFFICHAGE
# ============================================================

print("\n")
print("=" * 100)
print("TOP COMBINAISONS")
print("=" * 100)


for _, row in summary.head(15).iterrows():

    print(
        f"{row['Factor_A']:25s} + "
        f"{row['Factor_B']:25s} | "
        f"{int(row['Positive_Windows'])}/"
        f"{int(row['Windows'])} TEST positifs | "
        f"Avg "
        f"{row['Average_Test_PnL']:+7.3%} | "
        f"Win "
        f"{row['Average_Win_Rate']:6.1%} | "
        f"Trades "
        f"{int(row['Total_Test_Trades'])}"
    )


print("\n")
print("=" * 100)
print("FICHIERS CRÉÉS")
print("=" * 100)

print(
    "results/mean_reversion/factor_combo_walk_forward_results.csv"
)

print(
    "results/mean_reversion/factor_combo_walk_forward_summary.csv"
)