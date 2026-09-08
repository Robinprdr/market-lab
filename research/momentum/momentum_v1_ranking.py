import os
import numpy as np
import pandas as pd

# ============================================================
# MOMENTUM V1 - RANKING RESEARCH
# ============================================================

DATA_FILE = "results/momentum/momentum_v1_research.csv"
OUTPUT_DIR = "results/momentum"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(DATA_FILE)

df["Date"] = pd.to_datetime(df["Date"])

required = [
    "Date",
    "Ticker",
    "ATR_Pct",
    "Return_10D",
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
]

missing = [c for c in required if c not in df.columns]

if missing:
    raise ValueError(f"Colonnes manquantes : {missing}")

df = df.dropna(
    subset=[
        "ATR_Pct",
        "Return_10D",
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
    ]
).copy()


# ============================================================
# PÉRIODE
# ============================================================

df = df[
    (df["Date"] >= "2018-10-16")
    & (df["Date"] <= "2025-12-05")
].copy()


print("=" * 70)
print("MOMENTUM V1 - RANKING RESEARCH")
print("=" * 70)

print(f"Dataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")
print(
    f"Période : "
    f"{df['Date'].min().date()} -> "
    f"{df['Date'].max().date()}"
)


# ============================================================
# QUANTILES
# ============================================================

# Les quantiles sont calculés sur l'ensemble du dataset
# uniquement pour EXPLORER la relation entre intensité du
# signal et rendement futur.
#
# Ce résultat ne sera PAS utilisé directement comme validation
# finale. La validation finale devra rester walk-forward.

df["ATR_Q"] = pd.qcut(
    df["ATR_Pct"],
    q=5,
    labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
    duplicates="drop",
)

df["Return10_Q"] = pd.qcut(
    df["Return_10D"],
    q=5,
    labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
    duplicates="drop",
)


# ============================================================
# ANALYSE ATR
# ============================================================

print()
print("=" * 70)
print("1. ATR_PCT")
print("=" * 70)

atr_results = []

for q, group in df.groupby("ATR_Q", observed=True):

    row = {
        "Factor": "ATR_Pct",
        "Bucket": str(q),
        "Observations": len(group),
    }

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        row[f"Return_{horizon}D"] = group[col].mean()

        row[f"WinRate_{horizon}D"] = (
            group[col] > 0
        ).mean()

    atr_results.append(row)

atr_results = pd.DataFrame(atr_results)

print(atr_results.to_string(index=False))


# ============================================================
# ANALYSE RETURN 10D
# ============================================================

print()
print("=" * 70)
print("2. RETURN_10D")
print("=" * 70)

return10_results = []

for q, group in df.groupby("Return10_Q", observed=True):

    row = {
        "Factor": "Return_10D",
        "Bucket": str(q),
        "Observations": len(group),
    }

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        row[f"Return_{horizon}D"] = group[col].mean()

        row[f"WinRate_{horizon}D"] = (
            group[col] > 0
        ).mean()

    return10_results.append(row)

return10_results = pd.DataFrame(return10_results)

print(return10_results.to_string(index=False))


# ============================================================
# COMBINAISON ATR + RETURN10
# ============================================================

print()
print("=" * 70)
print("3. COMBINAISON ATR + RETURN_10D")
print("=" * 70)

# On crée une grille simple :
#
# ATR Q1-Q5
# Return10 Q1-Q5
#
# Cela permet de voir si les deux facteurs se renforcent
# réellement lorsqu'ils sont élevés simultanément.

combo_results = []

for atr_q in df["ATR_Q"].dropna().unique():

    for ret_q in df["Return10_Q"].dropna().unique():

        group = df[
            (df["ATR_Q"] == atr_q)
            & (df["Return10_Q"] == ret_q)
        ]

        if len(group) < 100:
            continue

        row = {
            "ATR_Q": str(atr_q),
            "Return10_Q": str(ret_q),
            "Observations": len(group),
        }

        for horizon in [1, 3, 5]:

            col = f"Future_Return_{horizon}D"

            row[f"Return_{horizon}D"] = group[col].mean()

            row[f"WinRate_{horizon}D"] = (
                group[col] > 0
            ).mean()

        combo_results.append(row)

combo_results = pd.DataFrame(combo_results)

print(combo_results.to_string(index=False))


# ============================================================
# SIGNALS FORTS
# ============================================================

print()
print("=" * 70)
print("4. SIGNALS FORTS")
print("=" * 70)

# Différents niveaux de sélection.
#
# L'idée est de voir ce qui arrive lorsqu'on exige que les
# deux facteurs soient simultanément élevés.

strong_results = []

for threshold in [0.60, 0.70, 0.80, 0.90]:

    atr_threshold = df["ATR_Pct"].quantile(threshold)
    ret_threshold = df["Return_10D"].quantile(threshold)

    strong = df[
        (df["ATR_Pct"] >= atr_threshold)
        & (df["Return_10D"] >= ret_threshold)
    ].copy()

    row = {
        "Quantile": threshold,
        "ATR_Threshold": atr_threshold,
        "Return10_Threshold": ret_threshold,
        "Observations": len(strong),
        "Pct_Dataset": len(strong) / len(df),
    }

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        row[f"Return_{horizon}D"] = strong[col].mean()

        row[f"WinRate_{horizon}D"] = (
            strong[col] > 0
        ).mean()

    strong_results.append(row)

strong_results = pd.DataFrame(strong_results)

print(strong_results.to_string(index=False))


# ============================================================
# SCORE SIMPLE DE RECHERCHE
# ============================================================

print()
print("=" * 70)
print("5. SCORE DE RECHERCHE")
print("=" * 70)

# ATTENTION :
# Ce score est UNIQUEMENT un outil d'exploration.
#
# On transforme chaque facteur en percentile puis on fait
# la moyenne.
#
# Exemple :
# ATR percentile = 0.90
# Return10 percentile = 0.80
# Score = 0.85
#
# Ce score n'est PAS encore le score du bot final.

df["ATR_Percentile"] = df["ATR_Pct"].rank(
    pct=True
)

df["Return10_Percentile"] = df["Return_10D"].rank(
    pct=True
)

df["Research_Score"] = (
    df["ATR_Percentile"]
    + df["Return10_Percentile"]
) / 2


df["Score_Q"] = pd.qcut(
    df["Research_Score"],
    q=5,
    labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
    duplicates="drop",
)

score_results = []

for q, group in df.groupby("Score_Q", observed=True):

    row = {
        "Score_Bucket": str(q),
        "Observations": len(group),
        "Average_Score": group["Research_Score"].mean(),
    }

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        row[f"Return_{horizon}D"] = group[col].mean()

        row[f"WinRate_{horizon}D"] = (
            group[col] > 0
        ).mean()

    score_results.append(row)

score_results = pd.DataFrame(score_results)

print(score_results.to_string(index=False))


# ============================================================
# TOP SIGNALS
# ============================================================

print()
print("=" * 70)
print("6. TOP 10% DES SIGNALS")
print("=" * 70)

top10_threshold = df["Research_Score"].quantile(0.90)

top10 = df[
    df["Research_Score"] >= top10_threshold
].copy()

print(
    f"Seuil score top 10% : "
    f"{top10_threshold:.4f}"
)

print(
    f"Observations : {len(top10):,} "
    f"({len(top10) / len(df):.2%} du dataset)"
)

for horizon in [1, 3, 5]:

    col = f"Future_Return_{horizon}D"

    print(
        f"{horizon}D : "
        f"Return moyen = {top10[col].mean():.3%} | "
        f"Win rate = {(top10[col] > 0).mean():.2%}"
    )


# ============================================================
# SAUVEGARDE
# ============================================================

atr_results.to_csv(
    f"{OUTPUT_DIR}/momentum_v1_ranking_atr.csv",
    index=False
)

return10_results.to_csv(
    f"{OUTPUT_DIR}/momentum_v1_ranking_return10.csv",
    index=False
)

combo_results.to_csv(
    f"{OUTPUT_DIR}/momentum_v1_ranking_combo.csv",
    index=False
)

strong_results.to_csv(
    f"{OUTPUT_DIR}/momentum_v1_ranking_strong.csv",
    index=False
)

score_results.to_csv(
    f"{OUTPUT_DIR}/momentum_v1_ranking_score.csv",
    index=False
)


print()
print("=" * 70)
print("FICHIERS CRÉÉS")
print("=" * 70)

print(
    "results/momentum/"
    "momentum_v1_ranking_atr.csv"
)

print(
    "results/momentum/"
    "momentum_v1_ranking_return10.csv"
)

print(
    "results/momentum/"
    "momentum_v1_ranking_combo.csv"
)

print(
    "results/momentum/"
    "momentum_v1_ranking_strong.csv"
)

print(
    "results/momentum/"
    "momentum_v1_ranking_score.csv"
)

print()
print("FIN")
