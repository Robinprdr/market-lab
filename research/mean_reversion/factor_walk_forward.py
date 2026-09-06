import pandas as pd
import numpy as np


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "results/mean_reversion/trades_autopsy.csv"

# Nous utilisons plusieurs fenêtres successives.
#
# Le TRAIN sert uniquement à déterminer les quartiles.
# Le TEST est ensuite évalué avec exactement les mêmes bornes.

WINDOWS = [

    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),

    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),

    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),

    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),

    ("2022-01-01", "2025-01-01", "2025-01-01", "2025-12-20"),
]


# ============================================================
# VARIABLES À ÉTUDIER
# ============================================================

FEATURES = [

    "Signal_Drop",
    "ATR_Pct",
    "Drop_ATR_Ratio",
    "Volume_Ratio",
    "Distance_SMA20",
    "Distance_SMA50",
    "Distance_SMA200",
    "Return_3D",
    "Return_5D",
    "Return_10D",
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio",
]


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(
    df["Date"]
)


# ============================================================
# FILTRE DE BASE
# ============================================================

# On conserve la règle déjà étudiée :
# exclusion des chutes supérieures à 4%.

df = df[
    df["Signal_Drop"] >= -0.04
].copy()


# ============================================================
# NETTOYAGE
# ============================================================

required = [
    "Date",
    "PnL_Pct"
] + FEATURES


missing = [
    col
    for col in required
    if col not in df.columns
]


if missing:

    print("\nERREUR : colonnes manquantes")
    print(missing)

    raise SystemExit


for col in FEATURES + ["PnL_Pct"]:

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )


df = df.dropna(
    subset=FEATURES + ["PnL_Pct"]
).copy()


# ============================================================
# FONCTION DE STATISTIQUES
# ============================================================

def avg_pnl(data):

    if len(data) == 0:
        return np.nan

    return (
        data["PnL_Pct"].mean()
        * 100
    )


def win_rate(data):

    if len(data) == 0:
        return np.nan

    return (
        (data["PnL_Pct"] > 0).mean()
        * 100
    )


# ============================================================
# TITRE
# ============================================================

print("\n" + "=" * 115)
print("FACTOR WALK-FORWARD — ROBUSTESSE DES VARIABLES")
print("=" * 115)

print("""
RÈGLE :

Pour chaque fenêtre :

1. Les quartiles sont calculés UNIQUEMENT sur TRAIN.
2. Ces mêmes bornes sont appliquées au TEST.
3. Nous ne choisissons aucun seuil précis.
4. Nous regardons si les mêmes zones restent favorables.

Le but est de mesurer la ROBUSTESSE,
pas de maximiser le rendement historique.
""")


# ============================================================
# STOCKAGE
# ============================================================

all_results = []


# ============================================================
# WALK-FORWARD
# ============================================================

for window_number, window in enumerate(
    WINDOWS,
    start=1
):

    train_start = window[0]
    train_end = window[1]
    test_start = window[2]
    test_end = window[3]


    train = df[
        (df["Date"] >= train_start) &
        (df["Date"] < train_end)
    ].copy()


    test = df[
        (df["Date"] >= test_start) &
        (df["Date"] < test_end)
    ].copy()


    print("\n")
    print("=" * 115)

    print(
        f"WINDOW {window_number}"
    )

    print(
        f"TRAIN : {train_start} → {train_end}"
    )

    print(
        f"TEST  : {test_start} → {test_end}"
    )

    print(
        f"Trades TRAIN : {len(train)}"
    )

    print(
        f"Trades TEST  : {len(test)}"
    )

    print("=" * 115)


    # ========================================================
    # CHAQUE VARIABLE
    # ========================================================

    for feature in FEATURES:

        try:

            quantiles = train[
                feature
            ].quantile(
                [0, 0.25, 0.50, 0.75, 1.0]
            ).values

        except Exception:

            continue


        quantiles = np.unique(
            quantiles
        )


        if len(quantiles) < 5:

            continue


        # ----------------------------------------------------
        # Attribution des quartiles
        # ----------------------------------------------------

        train["Bucket"] = pd.cut(
            train[feature],
            bins=quantiles,
            labels=False,
            include_lowest=True
        )


        test["Bucket"] = pd.cut(
            test[feature],
            bins=quantiles,
            labels=False,
            include_lowest=True
        )


        # ----------------------------------------------------
        # Moyennes TRAIN
        # ----------------------------------------------------

        train_stats = {}

        test_stats = {}


        for bucket in range(4):

            train_bucket = train[
                train["Bucket"] == bucket
            ]

            test_bucket = test[
                test["Bucket"] == bucket
            ]


            train_stats[bucket] = (
                avg_pnl(
                    train_bucket
                )
            )


            test_stats[bucket] = (
                avg_pnl(
                    test_bucket
                )
            )


            all_results.append({

                "Window":
                    window_number,

                "Feature":
                    feature,

                "Train_Start":
                    train_start,

                "Train_End":
                    train_end,

                "Test_Start":
                    test_start,

                "Test_End":
                    test_end,

                "Bucket":
                    bucket + 1,

                "Train_Trades":
                    len(train_bucket),

                "Train_Avg":
                    train_stats[bucket],

                "Test_Trades":
                    len(test_bucket),

                "Test_Avg":
                    test_stats[bucket],

                "Test_Win_Rate":
                    win_rate(
                        test_bucket
                    )
            })


        # ----------------------------------------------------
        # Identifier le meilleur quartile TRAIN
        # ----------------------------------------------------

        valid_train = {
            k: v
            for k, v in train_stats.items()
            if not pd.isna(v)
        }


        if len(valid_train) == 0:

            continue


        best_bucket = max(
            valid_train,
            key=valid_train.get
        )


        best_train_avg = (
            train_stats[best_bucket]
        )

        best_test_avg = (
            test_stats[best_bucket]
        )


        print(
            f"{feature:<28} | "
            f"TRAIN meilleur Q{best_bucket + 1} "
            f"{best_train_avg:+.3f}% | "
            f"TEST même Q "
            f"{best_test_avg:+.3f}%"
        )


# ============================================================
# NETTOYAGE
# ============================================================

if "Bucket" in train.columns:

    train.drop(
        columns=["Bucket"],
        inplace=True
    )

if "Bucket" in test.columns:

    test.drop(
        columns=["Bucket"],
        inplace=True
    )


# ============================================================
# RÉSULTATS
# ============================================================

results = pd.DataFrame(
    all_results
)


# ============================================================
# 1. STABILITÉ DES MEILLEURS QUARTILES
# ============================================================

print("\n" + "=" * 115)
print("1 — STABILITÉ DU MEILLEUR QUARTILE")
print("=" * 115)

print("""
Pour chaque fenêtre :

- on identifie le meilleur quartile dans TRAIN
- on regarde exactement ce même quartile dans TEST

C'est beaucoup plus strict qu'un simple classement
sur toute la période historique.
""")


summary = []


for feature in FEATURES:

    feature_data = results[
        results["Feature"] == feature
    ]


    confirmations = 0
    tests = 0

    train_values = []
    test_values = []


    for window_number in range(
        1,
        len(WINDOWS) + 1
    ):

        window_data = feature_data[
            feature_data["Window"] == window_number
        ]


        if len(window_data) == 0:
            continue


        best_train_row = (
            window_data
            .sort_values(
                "Train_Avg",
                ascending=False
            )
            .iloc[0]
        )


        best_bucket = (
            best_train_row["Bucket"]
        )


        selected_test = window_data[
            window_data["Bucket"]
            == best_bucket
        ]


        if len(selected_test) == 0:
            continue


        test_avg = (
            selected_test["Test_Avg"].iloc[0]
        )

        train_avg = (
            selected_test["Train_Avg"].iloc[0]
        )


        if pd.isna(test_avg):
            continue


        tests += 1

        train_values.append(
            train_avg
        )

        test_values.append(
            test_avg
        )


        if test_avg > 0:

            confirmations += 1


    confirmation_rate = (

        confirmations / tests * 100

        if tests > 0

        else np.nan
    )


    correlation = np.nan


    if len(train_values) >= 3:

        if (
            np.std(train_values) > 0
            and
            np.std(test_values) > 0
        ):

            correlation = np.corrcoef(
                train_values,
                test_values
            )[0, 1]


    summary.append({

        "Feature":
            feature,

        "Windows":
            tests,

        "Positive_Test_Windows":
            confirmations,

        "Positive_Test_%":
            confirmation_rate,

        "Train_Test_Correlation":
            correlation,

        "Avg_Selected_Train":
            np.mean(train_values)
            if train_values
            else np.nan,

        "Avg_Selected_Test":
            np.mean(test_values)
            if test_values
            else np.nan
    })


summary_df = pd.DataFrame(
    summary
)


print(
    f"\n"
    f"{'Variable':<28} | "
    f"{'Fenêtres':>8} | "
    f"{'TEST +':>7} | "
    f"{'% +':>7} | "
    f"{'Corr':>8} | "
    f"{'TEST Avg':>10}"
)

print("-" * 100)


for _, row in summary_df.iterrows():

    corr = row[
        "Train_Test_Correlation"
    ]

    corr_text = (
        f"{corr:+.3f}"
        if not pd.isna(corr)
        else "N/A"
    )


    print(
        f"{row['Feature']:<28} | "
        f"{row['Windows']:>8.0f} | "
        f"{row['Positive_Test_Windows']:>7.0f} | "
        f"{row['Positive_Test_%']:>6.1f}% | "
        f"{corr_text:>8} | "
        f"{row['Avg_Selected_Test']:>+9.3f}%"
    )


# ============================================================
# 2. RÉSULTATS PAR FENÊTRE
# ============================================================

print("\n" + "=" * 115)
print("2 — RÉSULTATS PAR FENÊTRE")
print("=" * 115)


for window_number in range(
    1,
    len(WINDOWS) + 1
):

    window_results = results[
        results["Window"] == window_number
    ]


    if len(window_results) == 0:
        continue


    print(
        f"\nWINDOW {window_number}"
    )

    print(
        f"{'Variable':<28} | "
        f"{'Q TRAIN':>8} | "
        f"{'TRAIN':>9} | "
        f"{'TEST':>9}"
    )

    print("-" * 70)


    for feature in FEATURES:

        feature_data = window_results[
            window_results["Feature"] == feature
        ]


        if len(feature_data) == 0:
            continue


        best_row = (
            feature_data
            .sort_values(
                "Train_Avg",
                ascending=False
            )
            .iloc[0]
        )


        print(
            f"{feature:<28} | "
            f"Q{int(best_row['Bucket']):>7} | "
            f"{best_row['Train_Avg']:>+8.3f}% | "
            f"{best_row['Test_Avg']:>+8.3f}%"
        )


# ============================================================
# EXPORT
# ============================================================

results.to_csv(
    "results/mean_reversion/factor_walk_forward_results.csv",
    index=False
)

summary_df.to_csv(
    "results/mean_reversion/factor_walk_forward_summary.csv",
    index=False
)


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 115)
print("FIN DU FACTOR WALK-FORWARD")
print("=" * 115)

print("""
FICHIERS CRÉÉS :

results/mean_reversion/factor_walk_forward_results.csv
results/mean_reversion/factor_walk_forward_summary.csv

IMPORTANT :

Nous ne créons toujours AUCUN score.

Une variable ne sera considérée comme potentiellement
intéressante que si son comportement survit de manière
répétée dans les différentes fenêtres.

Même une variable avec un excellent résultat historique
sera rejetée si son comportement s'inverse régulièrement.
""")