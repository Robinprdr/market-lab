import pandas as pd
import numpy as np


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "results/mean_reversion/trades_autopsy.csv"

TEST_START = "2021-01-01"
TEST_END = "2025-12-20"


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(df["Date"])

df = df[
    (df["Date"] >= TEST_START) &
    (df["Date"] < TEST_END)
].copy()


# ============================================================
# NOTRE STRATÉGIE ACTUELLE
# ============================================================

# On exclut les chutes > 4%
df = df[df["Signal_Drop"] >= -0.04].copy()


# ============================================================
# IDENTIFICATION DES COLONNES SPY
# ============================================================

print("\n" + "=" * 110)
print("ANALYSE DES RÉGIMES SPY")
print("=" * 110)

print("\nColonnes disponibles :")
print(", ".join(df.columns))


# ============================================================
# VÉRIFICATION
# ============================================================

spy_columns = [
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio"
]

missing = [
    col for col in spy_columns
    if col not in df.columns
]

if missing:

    print("\nERREUR : colonnes SPY manquantes :")
    print(missing)

    print("""
Ton fichier results/mean_reversion/trades_autopsy.csv ne contient pas encore
toutes les données SPY nécessaires.

Dans ce cas, ne modifie rien et envoie-moi simplement
ce résultat.
""")

    raise SystemExit


# ============================================================
# NETTOYAGE
# ============================================================

for col in spy_columns:
    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )

df = df.dropna(
    subset=spy_columns + ["PnL_Pct"]
).copy()


# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse(data, label):

    if len(data) == 0:
        print(
            f"{label:<55} | aucun trade"
        )
        return

    win_rate = (
        (data["PnL_Pct"] > 0).mean()
        * 100
    )

    avg_pnl = (
        data["PnL_Pct"].mean()
        * 100
    )

    total_pnl = (
        data["PnL_Pct"].sum()
        * 100
    )

    print(
        f"{label:<55} | "
        f"{len(data):>4} trades | "
        f"Win {win_rate:>5.1f}% | "
        f"Avg {avg_pnl:>7.3f}% | "
        f"Somme {total_pnl:>8.2f}%"
    )


# ============================================================
# 1. SPY HAUSSE / BAISSE
# ============================================================

print("\n" + "=" * 110)
print("1 — SPY : JOUR DE HAUSSE VS JOUR DE BAISSE")
print("=" * 110)

spy_up = df[
    df["SPY_Return"] > 0
]

spy_down = df[
    df["SPY_Return"] < 0
]

spy_flat = df[
    df["SPY_Return"] == 0
]

analyse(
    spy_up,
    "SPY en hausse"
)

analyse(
    spy_down,
    "SPY en baisse"
)

analyse(
    spy_flat,
    "SPY stable"
)


# ============================================================
# 2. INTENSITÉ DU MOUVEMENT SPY
# ============================================================

print("\n" + "=" * 110)
print("2 — INTENSITÉ DU MOUVEMENT SPY")
print("=" * 110)

conditions_spy_return = {

    "SPY baisse > 2%":
        df["SPY_Return"] < -0.02,

    "SPY baisse 1 à 2%":
        (df["SPY_Return"] >= -0.02) &
        (df["SPY_Return"] < -0.01),

    "SPY entre -1% et +1%":
        (df["SPY_Return"] >= -0.01) &
        (df["SPY_Return"] <= 0.01),

    "SPY hausse 1 à 2%":
        (df["SPY_Return"] > 0.01) &
        (df["SPY_Return"] <= 0.02),

    "SPY hausse > 2%":
        df["SPY_Return"] > 0.02,
}

for label, condition in conditions_spy_return.items():

    analyse(
        df[condition],
        label
    )


# ============================================================
# 3. SPY AU-DESSUS / EN-DESSOUS SMA50
# ============================================================

print("\n" + "=" * 110)
print("3 — SPY PAR RAPPORT À SA SMA50")
print("=" * 110)

spy_above_50 = df[
    df["SPY_Distance_SMA50"] > 0
]

spy_below_50 = df[
    df["SPY_Distance_SMA50"] < 0
]

analyse(
    spy_above_50,
    "SPY au-dessus SMA50"
)

analyse(
    spy_below_50,
    "SPY sous SMA50"
)


# ============================================================
# 4. DISTANCE À LA SMA50
# ============================================================

print("\n" + "=" * 110)
print("4 — DISTANCE SPY / SMA50")
print("=" * 110)

conditions_distance = {

    "SPY très sous SMA50 (< -5%)":
        df["SPY_Distance_SMA50"] < -0.05,

    "SPY sous SMA50 (-5% à 0%)":
        (df["SPY_Distance_SMA50"] >= -0.05) &
        (df["SPY_Distance_SMA50"] < 0),

    "SPY légèrement au-dessus (0 à +5%)":
        (df["SPY_Distance_SMA50"] >= 0) &
        (df["SPY_Distance_SMA50"] <= 0.05),

    "SPY au-dessus (+5 à +10%)":
        (df["SPY_Distance_SMA50"] > 0.05) &
        (df["SPY_Distance_SMA50"] <= 0.10),

    "SPY très au-dessus (> +10%)":
        df["SPY_Distance_SMA50"] > 0.10,
}

for label, condition in conditions_distance.items():

    analyse(
        df[condition],
        label
    )


# ============================================================
# 5. VOLUME SPY
# ============================================================

print("\n" + "=" * 110)
print("5 — VOLUME SPY")
print("=" * 110)

volume_conditions = {

    "SPY volume < moyenne":
        df["SPY_Volume_Ratio"] < 1,

    "SPY volume 1 à 1.5x":
        (df["SPY_Volume_Ratio"] >= 1) &
        (df["SPY_Volume_Ratio"] < 1.5),

    "SPY volume 1.5 à 2x":
        (df["SPY_Volume_Ratio"] >= 1.5) &
        (df["SPY_Volume_Ratio"] < 2),

    "SPY volume > 2x":
        df["SPY_Volume_Ratio"] >= 2,
}

for label, condition in volume_conditions.items():

    analyse(
        df[condition],
        label
    )


# ============================================================
# 6. COMBINAISONS DE RÉGIME
# ============================================================

print("\n" + "=" * 110)
print("6 — COMBINAISONS DE RÉGIME")
print("=" * 110)


regimes = {

    "SPY baisse + SPY sous SMA50":
        (df["SPY_Return"] < 0) &
        (df["SPY_Distance_SMA50"] < 0),

    "SPY baisse + SPY au-dessus SMA50":
        (df["SPY_Return"] < 0) &
        (df["SPY_Distance_SMA50"] > 0),

    "SPY hausse + SPY au-dessus SMA50":
        (df["SPY_Return"] > 0) &
        (df["SPY_Distance_SMA50"] > 0),

    "SPY hausse + SPY sous SMA50":
        (df["SPY_Return"] > 0) &
        (df["SPY_Distance_SMA50"] < 0),

    "SPY baisse >2% + volume >2x":
        (df["SPY_Return"] < -0.02) &
        (df["SPY_Volume_Ratio"] > 2),

    "SPY baisse + volume >1.5x":
        (df["SPY_Return"] < 0) &
        (df["SPY_Volume_Ratio"] > 1.5),
}

for label, condition in regimes.items():

    analyse(
        df[condition],
        label
    )


# ============================================================
# 7. COMPARAISON AVEC LE MARCHÉ CALME
# ============================================================

print("\n" + "=" * 110)
print("7 — MARCHÉ CALME VS MARCHÉ SOUS PRESSION")
print("=" * 110)

calm = (
    df["SPY_Return"].abs() < 0.01
)

pressure = (
    df["SPY_Return"] < -0.01
)

panic = (
    df["SPY_Return"] < -0.02
)

analyse(
    df[calm],
    "SPY mouvement < 1%"
)

analyse(
    df[pressure],
    "SPY baisse > 1%"
)

analyse(
    df[panic],
    "SPY baisse > 2%"
)


# ============================================================
# 8. STATISTIQUES GÉNÉRALES
# ============================================================

print("\n" + "=" * 110)
print("8 — STATISTIQUES GÉNÉRALES")
print("=" * 110)

print(
    f"\nTrades analysés : {len(df)}"
)

print(
    f"SPY Return moyen : "
    f"{df['SPY_Return'].mean() * 100:.3f}%"
)

print(
    f"SPY Distance SMA50 moyenne : "
    f"{df['SPY_Distance_SMA50'].mean() * 100:.3f}%"
)

print(
    f"SPY Volume Ratio moyen : "
    f"{df['SPY_Volume_Ratio'].mean():.2f}x"
)


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 110)
print("FIN DE L'ANALYSE DES RÉGIMES")
print("=" * 110)

print("""
IMPORTANT :

Nous ne choisissons encore AUCUN filtre.

Cette analyse sert uniquement à découvrir des régimes
potentiellement favorables ou défavorables.

Une condition qui semble excellente ici devra ensuite
être testée hors échantillon avant d'être intégrée
à la stratégie.
""")