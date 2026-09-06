import pandas as pd
import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================

TRADES_FILE = "trades_autopsy.csv"

INITIAL_CAPITAL = 10_000

# Signal de base
DROP_THRESHOLD = -0.04

# Gestion du risque
STOP_LOSS = -0.02
TAKE_PROFIT = 0.04
MAX_HOLDING_DAYS = 5

# Capital maximum engagé par position
ALLOCATION = 0.20

# Nombre maximum de positions simultanées
MAX_POSITIONS = 5


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(TRADES_FILE)

df["Date"] = pd.to_datetime(df["Date"])

# Filtre de base
df = df[
    df["Signal_Drop"] >= DROP_THRESHOLD
].copy()


# ============================================================
# SCORE
# ============================================================
#
# IMPORTANT :
# Ce score est volontairement SIMPLE.
#
# Il ne cherche pas à maximiser les résultats historiques.
# Il sert à créer une première architecture de scoring.
#
# Chaque facteur donne 0 ou 1 point.
#
# Maximum = 5 points.
#
# ============================================================


def calculate_score(row):

    score = 0

    # --------------------------------------------------------
    # 1. Distance SMA20
    # --------------------------------------------------------
    #
    # On préfère une action qui vient de corriger
    # mais qui reste relativement proche de sa tendance.
    #
    if 0 <= row["Distance_SMA20"] <= 0.10:
        score += 1

    # --------------------------------------------------------
    # 2. Distance SMA50
    # --------------------------------------------------------
    #
    # Même logique :
    # éviter les situations extrêmement éloignées.
    #
    if 0 <= row["Distance_SMA50"] <= 0.20:
        score += 1

    # --------------------------------------------------------
    # 3. Retour 3 jours
    # --------------------------------------------------------
    #
    # On cherche une correction récente.
    #
    if row["Return_3D"] < 0:
        score += 1

    # --------------------------------------------------------
    # 4. Drop / ATR
    # --------------------------------------------------------
    #
    # Le mouvement doit être suffisamment important
    # par rapport à la volatilité normale.
    #
    if row["Drop_ATR_Ratio"] >= 1:
        score += 1

    # --------------------------------------------------------
    # 5. Contexte SPY
    # --------------------------------------------------------
    #
    # On évite les journées où le marché global
    # est en forte chute.
    #
    if row["SPY_Return"] > -0.02:
        score += 1

    return score


df["Score"] = df.apply(calculate_score, axis=1)


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_score(score):

    if score >= 4:
        return "HIGH"

    if score >= 3:
        return "MEDIUM"

    return "LOW"


df["Score_Level"] = df["Score"].apply(classify_score)


# ============================================================
# ANALYSE DES SCORES
# ============================================================

print("=" * 70)
print("STRATEGY V1 - SCORE ANALYSIS")
print("=" * 70)

print(f"\nTrades analysés : {len(df)}")

print("\nRépartition des scores :")

score_distribution = (
    df["Score"]
    .value_counts()
    .sort_index()
)

for score, count in score_distribution.items():

    percentage = count / len(df)

    print(
        f"  Score {score}/5 : "
        f"{count} trades "
        f"({percentage:.1%})"
    )


# ============================================================
# PERFORMANCE PAR SCORE
# ============================================================

print("\n")
print("=" * 70)
print("PERFORMANCE PAR SCORE")
print("=" * 70)

for score in sorted(df["Score"].unique()):

    subset = df[df["Score"] == score]

    pnl = subset["PnL_Pct"]

    if len(subset) == 0:
        continue

    win_rate = (pnl > 0).mean()
    avg_pnl = pnl.mean()
    median_pnl = pnl.median()
    total_pnl = pnl.sum()

    print(
        f"\nScore {score}/5"
    )

    print(
        f"  Trades   : {len(subset)}"
    )

    print(
        f"  Win rate : {win_rate:.1%}"
    )

    print(
        f"  Moyenne  : {avg_pnl:.3%}"
    )

    print(
        f"  Médiane  : {median_pnl:.3%}"
    )

    print(
        f"  Total    : {total_pnl:.2%}"
    )


# ============================================================
# HIGH vs ALL
# ============================================================

print("\n")
print("=" * 70)
print("HIGH CONFIDENCE VS BASE")
print("=" * 70)

base_pnl = df["PnL_Pct"]

high = df[
    df["Score"] >= 4
]

high_pnl = high["PnL_Pct"]


def print_stats(name, pnl):

    if len(pnl) == 0:
        return

    print(f"\n{name}")

    print(f"  Trades   : {len(pnl)}")
    print(f"  Win rate : {(pnl > 0).mean():.1%}")
    print(f"  Moyenne  : {pnl.mean():.3%}")
    print(f"  Médiane  : {pnl.median():.3%}")
    print(f"  Total    : {pnl.sum():.2%}")


print_stats("BASE", base_pnl)

print_stats("HIGH >= 4/5", high_pnl)


# ============================================================
# PERFORMANCE ANNUELLE
# ============================================================

print("\n")
print("=" * 70)
print("PERFORMANCE ANNUELLE")
print("=" * 70)

df["Year"] = df["Date"].dt.year

for year in sorted(df["Year"].unique()):

    yearly = df[
        df["Year"] == year
    ]

    base = yearly["PnL_Pct"]

    high = yearly[
        yearly["Score"] >= 4
    ]["PnL_Pct"]

    print(f"\n{year}")

    print(
        f"  BASE : "
        f"{len(base)} trades | "
        f"Win {(base > 0).mean():.1%} | "
        f"Avg {base.mean():.3%} | "
        f"Total {base.sum():.2%}"
    )

    if len(high) > 0:

        print(
            f"  HIGH : "
            f"{len(high)} trades | "
            f"Win {(high > 0).mean():.1%} | "
            f"Avg {high.mean():.3%} | "
            f"Total {high.sum():.2%}"
        )

    else:

        print(
            "  HIGH : aucun trade"
        )


# ============================================================
# EXPORT
# ============================================================

df.to_csv(
    "strategy_v1_scored_trades.csv",
    index=False
)

print("\n")
print("=" * 70)
print("FICHIER CRÉÉ")
print("=" * 70)

print("✓ strategy_v1_scored_trades.csv")

print("\nTerminé.")