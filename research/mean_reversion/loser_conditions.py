import pandas as pd
import numpy as np

# ============================================================
# CHARGEMENT
# ============================================================

trades = pd.read_csv("results/mean_reversion/trades_autopsy.csv")

print("=" * 70)
print("RECHERCHE DES CONDITIONS QUI PRÉCÈDENT LES PERDANTS")
print("=" * 70)

print(f"\nTrades analysés : {len(trades)}")

# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse_condition(name, condition):

    subset = trades[condition].copy()

    if len(subset) == 0:
        return

    winners = (subset["PnL_Pct"] > 0).sum()
    losers = (subset["PnL_Pct"] < 0).sum()

    win_rate = winners / len(subset)

    avg_pnl = subset["PnL_Pct"].mean()

    loss_rate = losers / len(subset)

    print(
        f"{name:45s} | "
        f"{len(subset):4d} trades | "
        f"Win {win_rate:6.1%} | "
        f"Loss {loss_rate:6.1%} | "
        f"PnL {avg_pnl:+.3%}"
    )


# ============================================================
# CONDITIONS INDIVIDUELLES
# ============================================================

print("\n" + "=" * 70)
print("1. CONDITIONS INDIVIDUELLES")
print("=" * 70)

conditions = [

    ("Chute > 4%", trades["Signal_Drop"] < -0.04),

    ("Chute entre -4% et -3%",
     (trades["Signal_Drop"] >= -0.04) &
     (trades["Signal_Drop"] < -0.03)),

    ("Chute entre -3% et -2.5%",
     (trades["Signal_Drop"] >= -0.03) &
     (trades["Signal_Drop"] < -0.025)),

    ("Chute entre -2.5% et -2%",
     (trades["Signal_Drop"] >= -0.025) &
     (trades["Signal_Drop"] <= -0.02)),

    ("Chute < 3%",
     trades["Signal_Drop"] > -0.03),

    ("Chute / ATR < 0.5",
     trades["Drop_ATR_Ratio"] < 0.5),

    ("Chute / ATR 0.5-1",
     (trades["Drop_ATR_Ratio"] >= 0.5) &
     (trades["Drop_ATR_Ratio"] < 1)),

    ("Chute / ATR 1-1.5",
     (trades["Drop_ATR_Ratio"] >= 1) &
     (trades["Drop_ATR_Ratio"] < 1.5)),

    ("Chute / ATR > 1.5",
     trades["Drop_ATR_Ratio"] > 1.5),

    ("Volume > 2x",
     trades["Volume_Ratio"] > 2),

    ("Volume 1.5-2x",
     (trades["Volume_Ratio"] >= 1.5) &
     (trades["Volume_Ratio"] < 2)),

    ("Volume 1.25-1.5x",
     (trades["Volume_Ratio"] >= 1.25) &
     (trades["Volume_Ratio"] < 1.5)),

    ("Prix < SMA200",
     trades["Distance_SMA200"] < 0),

    ("Distance SMA50 < 2%",
     trades["Distance_SMA50"] < 0.02),

    ("Distance SMA50 > 10%",
     trades["Distance_SMA50"] > 0.10),

    ("Distance SMA50 > 20%",
     trades["Distance_SMA50"] > 0.20),

    ("Baisse 3 jours",
     trades["Return_3D"] < 0),

    ("Baisse 5 jours",
     trades["Return_5D"] < 0),

    ("Baisse 5 jours > -5%",
     trades["Return_5D"] < -0.05),

    ("Baisse 10 jours",
     trades["Return_10D"] < 0),

    ("Au moins 3 jours rouges / 5",
     trades["Negative_Days_5"] >= 3),

    ("Au moins 4 jours rouges / 5",
     trades["Negative_Days_5"] >= 4),
]

for name, condition in conditions:
    analyse_condition(name, condition)


# ============================================================
# COMBINAISONS
# ============================================================

print("\n" + "=" * 70)
print("2. COMBINAISONS DE RED FLAGS")
print("=" * 70)

combinations = [

    (
        "Baisse 5J + 3 jours rouges",
        (trades["Return_5D"] < 0) &
        (trades["Negative_Days_5"] >= 3)
    ),

    (
        "Baisse 5J > -5% + 3 jours rouges",
        (trades["Return_5D"] < -0.05) &
        (trades["Negative_Days_5"] >= 3)
    ),

    (
        "Chute > 4% + volume > 2x",
        (trades["Signal_Drop"] < -0.04) &
        (trades["Volume_Ratio"] > 2)
    ),

    (
        "Chute > 4% + ratio ATR > 1.5",
        (trades["Signal_Drop"] < -0.04) &
        (trades["Drop_ATR_Ratio"] > 1.5)
    ),

    (
        "Prix < SMA200 + baisse 5J",
        (trades["Distance_SMA200"] < 0) &
        (trades["Return_5D"] < 0)
    ),

    (
        "Prix < SMA200 + 3 jours rouges",
        (trades["Distance_SMA200"] < 0) &
        (trades["Negative_Days_5"] >= 3)
    ),

    (
        "Baisse 5J + chute > 4%",
        (trades["Return_5D"] < 0) &
        (trades["Signal_Drop"] < -0.04)
    ),

    (
        "Baisse 5J + volume > 2x",
        (trades["Return_5D"] < 0) &
        (trades["Volume_Ratio"] > 2)
    ),

    (
        "3 jours rouges + volume > 2x",
        (trades["Negative_Days_5"] >= 3) &
        (trades["Volume_Ratio"] > 2)
    ),

    (
        "3 jours rouges + chute > 4%",
        (trades["Negative_Days_5"] >= 3) &
        (trades["Signal_Drop"] < -0.04)
    ),

    (
        "3 jours rouges + ratio ATR > 1.5",
        (trades["Negative_Days_5"] >= 3) &
        (trades["Drop_ATR_Ratio"] > 1.5)
    ),

    (
        "SMA200 négative + baisse 5J + 3 jours rouges",
        (trades["Distance_SMA200"] < 0) &
        (trades["Return_5D"] < 0) &
        (trades["Negative_Days_5"] >= 3)
    ),

    (
        "Chute > 4% + volume > 2x + baisse 5J",
        (trades["Signal_Drop"] < -0.04) &
        (trades["Volume_Ratio"] > 2) &
        (trades["Return_5D"] < 0)
    ),

    (
        "Chute > 4% + 3 jours rouges + baisse 5J",
        (trades["Signal_Drop"] < -0.04) &
        (trades["Negative_Days_5"] >= 3) &
        (trades["Return_5D"] < 0)
    ),
]

for name, condition in combinations:
    analyse_condition(name, condition)


# ============================================================
# COMPARAISON AVEC LA BASE
# ============================================================

print("\n" + "=" * 70)
print("3. RÉFÉRENCE")
print("=" * 70)

base_win = (trades["PnL_Pct"] > 0).mean()
base_pnl = trades["PnL_Pct"].mean()

print(f"Taux de réussite global : {base_win:.1%}")
print(f"PnL moyen global        : {base_pnl:+.3%}")


# ============================================================
# EXPORT
# ============================================================

print("\n" + "=" * 70)
print("Analyse terminée.")
print("=" * 70)