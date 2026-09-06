import pandas as pd
import numpy as np


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "trades_autopsy.csv"

# IMPORTANT :
# TRAIN = période utilisée pour découvrir les relations
# TEST  = période laissée de côté pour vérifier ces relations
#
# Nous ne choisissons PAS les seuils à partir du TEST.

TRAIN_START = "2018-01-01"
TRAIN_END = "2022-01-01"

TEST_START = "2022-01-01"
TEST_END = "2025-12-20"


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(df["Date"])


# ============================================================
# FILTRE DE BASE
# ============================================================

# On conserve uniquement les setups que nous avons déjà
# décidé d'étudier :
# exclusion des chutes supérieures à 4%.

df = df[
    df["Signal_Drop"] >= -0.04
].copy()


# ============================================================
# COLONNES NÉCESSAIRES
# ============================================================

features = [
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
    "Negative_Days_5",
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio"
]

required = [
    "Date",
    "PnL_Pct"
] + features


missing = [
    col
    for col in required
    if col not in df.columns
]

if missing:

    print("\n" + "=" * 110)
    print("ERREUR : COLONNES MANQUANTES")
    print("=" * 110)

    print("\nColonnes manquantes :")
    print(missing)

    raise SystemExit


# ============================================================
# NETTOYAGE
# ============================================================

for col in features + ["PnL_Pct"]:

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )


df = df.dropna(
    subset=features + ["PnL_Pct"]
).copy()


# ============================================================
# SÉPARATION TRAIN / TEST
# ============================================================

train = df[
    (df["Date"] >= TRAIN_START) &
    (df["Date"] < TRAIN_END)
].copy()

test = df[
    (df["Date"] >= TEST_START) &
    (df["Date"] < TEST_END)
].copy()


# ============================================================
# TITRE
# ============================================================

print("\n" + "=" * 110)
print("ANALYSE DES FACTEURS — TRAIN / TEST")
print("=" * 110)

print(
    f"\nTRAIN : {TRAIN_START} → {TRAIN_END}"
)

print(
    f"TEST  : {TEST_START} → {TEST_END}"
)

print(
    f"\nTrades TRAIN : {len(train)}"
)

print(
    f"Trades TEST  : {len(test)}"
)

print("""
IMPORTANT :

Cette analyse ne crée aucun nouveau filtre.

Elle cherche uniquement à déterminer si certaines
caractéristiques des setups semblent liées au résultat.

Les résultats TEST servent uniquement à vérifier
si les observations découvertes dans TRAIN survivent
sur des données qui n'ont pas servi à les découvrir.
""")


# ============================================================
# FONCTION STATISTIQUE
# ============================================================

def stats(data):

    if len(data) == 0:

        return {
            "Trades": 0,
            "Win_Rate": np.nan,
            "Avg_PnL": np.nan,
            "Median_PnL": np.nan,
            "Total_PnL": np.nan
        }

    return {
        "Trades": len(data),

        "Win_Rate":
            (data["PnL_Pct"] > 0).mean() * 100,

        "Avg_PnL":
            data["PnL_Pct"].mean() * 100,

        "Median_PnL":
            data["PnL_Pct"].median() * 100,

        "Total_PnL":
            data["PnL_Pct"].sum() * 100
    }


# ============================================================
# ANALYSE PAR QUARTILES
# ============================================================

print("\n" + "=" * 110)
print("1 — FACTEURS : ANALYSE PAR QUARTILES")
print("=" * 110)

print("""
Pour chaque variable, nous découpons les trades TRAIN
en 4 groupes de taille comparable.

Cela permet d'éviter de choisir arbitrairement un seuil.

Nous regardons ensuite si les groupes les plus favorables
dans TRAIN présentent également un comportement favorable
dans TEST.
""")


all_results = []


for feature in features:

    print("\n" + "-" * 110)
    print(f"VARIABLE : {feature}")
    print("-" * 110)

    # --------------------------------------------------------
    # Quartiles calculés UNIQUEMENT sur TRAIN
    # --------------------------------------------------------

    try:

        train_quartiles = pd.qcut(
            train[feature],
            q=4,
            duplicates="drop"
        )

    except Exception:

        print(
            "Impossible de créer les quartiles."
        )

        continue


    # --------------------------------------------------------
    # Bornes TRAIN
    # --------------------------------------------------------

    bins = train[feature].quantile(
        [0, 0.25, 0.50, 0.75, 1.0]
    ).values

    bins = np.unique(bins)

    if len(bins) < 5:

        print(
            "Pas assez de valeurs distinctes."
        )

        continue


    # --------------------------------------------------------
    # Application des mêmes bornes au TRAIN
    # --------------------------------------------------------

    train["TEMP_BUCKET"] = pd.cut(
        train[feature],
        bins=bins,
        include_lowest=True,
        duplicates="drop"
    )


    # --------------------------------------------------------
    # Application des mêmes bornes au TEST
    # --------------------------------------------------------

    test["TEMP_BUCKET"] = pd.cut(
        test[feature],
        bins=bins,
        include_lowest=True,
        duplicates="drop"
    )


    # --------------------------------------------------------
    # Affichage
    # --------------------------------------------------------

    print(
        f"\n{'Quartile TRAIN':<25} | "
        f"{'TRAIN trades':>12} | "
        f"{'TRAIN avg':>11} | "
        f"{'TEST trades':>11} | "
        f"{'TEST avg':>10}"
    )

    print("-" * 110)


    train_groups = (
        train.groupby(
            "TEMP_BUCKET",
            observed=True
        )
    )

    test_groups = (
        test.groupby(
            "TEMP_BUCKET",
            observed=True
        )
    )


    for bucket in train_groups.groups:

        train_group = train_groups.get_group(
            bucket
        )

        if bucket in test_groups.groups:

            test_group = test_groups.get_group(
                bucket
            )

        else:

            test_group = test.iloc[0:0]


        train_avg = (
            train_group["PnL_Pct"].mean()
            * 100
        )

        test_avg = (
            test_group["PnL_Pct"].mean()
            * 100
            if len(test_group) > 0
            else np.nan
        )


        print(
            f"{str(bucket):<25} | "
            f"{len(train_group):>12} | "
            f"{train_avg:>+10.3f}% | "
            f"{len(test_group):>11} | "
            f"{test_avg:>+9.3f}%"
        )


        all_results.append({

            "Feature": feature,

            "Bucket": str(bucket),

            "Train_Trades":
                len(train_group),

            "Train_Win_Rate":
                (train_group["PnL_Pct"] > 0).mean() * 100,

            "Train_Avg_PnL":
                train_avg,

            "Test_Trades":
                len(test_group),

            "Test_Win_Rate":
                (
                    (test_group["PnL_Pct"] > 0).mean() * 100
                    if len(test_group) > 0
                    else np.nan
                ),

            "Test_Avg_PnL":
                test_avg
        })


# ============================================================
# NETTOYAGE TEMPORAIRE
# ============================================================

if "TEMP_BUCKET" in train.columns:
    train.drop(
        columns=["TEMP_BUCKET"],
        inplace=True
    )

if "TEMP_BUCKET" in test.columns:
    test.drop(
        columns=["TEMP_BUCKET"],
        inplace=True
    )


# ============================================================
# 2 — STABILITÉ DES FACTEURS
# ============================================================

print("\n" + "=" * 110)
print("2 — STABILITÉ TRAIN → TEST")
print("=" * 110)

print("""
Ici nous cherchons quelque chose de très important :

Si une variable semble favorable dans TRAIN,
est-ce que les mêmes zones restent favorables dans TEST ?

Nous ne cherchons PAS le meilleur chiffre absolu.

Nous cherchons la répétition du comportement.
""")


summary = []


for feature in features:

    feature_results = [
        row
        for row in all_results
        if row["Feature"] == feature
    ]


    if len(feature_results) == 0:
        continue


    train_avgs = [
        row["Train_Avg_PnL"]
        for row in feature_results
    ]

    test_avgs = [
        row["Test_Avg_PnL"]
        for row in feature_results
        if not pd.isna(row["Test_Avg_PnL"])
    ]


    # --------------------------------------------------------
    # Corrélation TRAIN / TEST
    # --------------------------------------------------------

    correlation = np.nan

    if len(test_avgs) == len(train_avgs):

        if (
            np.std(train_avgs) > 0 and
            np.std(test_avgs) > 0
        ):

            correlation = np.corrcoef(
                train_avgs,
                test_avgs
            )[0, 1]


    # --------------------------------------------------------
    # Même signe
    # --------------------------------------------------------

    same_sign = 0

    comparable = 0


    for row in feature_results:

        train_value = row["Train_Avg_PnL"]
        test_value = row["Test_Avg_PnL"]


        if pd.isna(test_value):
            continue


        comparable += 1


        if (
            np.sign(train_value) ==
            np.sign(test_value)
        ):

            same_sign += 1


    stability = (
        same_sign / comparable * 100
        if comparable > 0
        else np.nan
    )


    summary.append({

        "Feature": feature,

        "Train_Test_Correlation":
            correlation,

        "Same_Sign_%":
            stability
    })


summary_df = pd.DataFrame(
    summary
)


print(
    f"\n"
    f"{'Variable':<28} | "
    f"{'Corr TRAIN/TEST':>16} | "
    f"{'Même signe':>12}"
)

print("-" * 75)


for _, row in summary_df.iterrows():

    correlation = row[
        "Train_Test_Correlation"
    ]

    stability = row[
        "Same_Sign_%"
    ]


    correlation_text = (
        f"{correlation:+.3f}"
        if not pd.isna(correlation)
        else "N/A"
    )

    stability_text = (
        f"{stability:.1f}%"
        if not pd.isna(stability)
        else "N/A"
    )


    print(
        f"{row['Feature']:<28} | "
        f"{correlation_text:>16} | "
        f"{stability_text:>12}"
    )


# ============================================================
# 3 — ANALYSE GAGNANTS / PERDANTS
# ============================================================

print("\n" + "=" * 110)
print("3 — DIFFÉRENCE GAGNANTS VS PERDANTS — TRAIN")
print("=" * 110)

print(
    f"\n{'Variable':<28} | "
    f"{'Gagnants':>12} | "
    f"{'Perdants':>12} | "
    f"{'Différence':>12}"
)

print("-" * 80)


winners = train[
    train["PnL_Pct"] > 0
]

losers = train[
    train["PnL_Pct"] <= 0
]


for feature in features:

    winner_mean = (
        winners[feature].mean()
    )

    loser_mean = (
        losers[feature].mean()
    )

    difference = (
        winner_mean - loser_mean
    )


    print(
        f"{feature:<28} | "
        f"{winner_mean:>12.4f} | "
        f"{loser_mean:>12.4f} | "
        f"{difference:>+12.4f}"
    )


# ============================================================
# 4 — TEST DES ANNÉES DU TEST
# ============================================================

print("\n" + "=" * 110)
print("4 — PERFORMANCE GLOBALE DU TEST PAR ANNÉE")
print("=" * 110)


for year in sorted(
    test["Date"].dt.year.unique()
):

    year_data = test[
        test["Date"].dt.year == year
    ]

    s = stats(
        year_data
    )


    print(
        f"{year} | "
        f"{s['Trades']:>4} trades | "
        f"Win {s['Win_Rate']:>5.1f}% | "
        f"Avg {s['Avg_PnL']:>+7.3f}% | "
        f"Somme {s['Total_PnL']:>+8.2f}%"
    )


# ============================================================
# 5 — EXPORTS
# ============================================================

results_df = pd.DataFrame(
    all_results
)

results_df.to_csv(
    "score_factor_results.csv",
    index=False
)

summary_df.to_csv(
    "score_factor_stability.csv",
    index=False
)


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 110)
print("FIN DE L'ANALYSE DES FACTEURS")
print("=" * 110)

print("""
FICHIERS CRÉÉS :

score_factor_results.csv
score_factor_stability.csv

IMPORTANT :

Nous n'avons encore créé AUCUN score de trading.

Cette étape sert uniquement à identifier des facteurs
potentiellement robustes.

La prochaine étape ne sera autorisée que si nous trouvons
des relations qui :

- existent dans TRAIN
- survivent dans TEST
- disposent d'un nombre suffisant de trades
- restent cohérentes sur plusieurs années

Nous éviterons volontairement les seuils ultra-précis
et les combinaisons complexes.
""")