import pandas as pd
import numpy as np

# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv("results/mean_reversion/all_trades.csv")

print("\n" + "=" * 70)
print("AUTOPSIE DES TRADES")
print("=" * 70)

print(f"\nNombre total de trades : {len(df)}")


# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse(groupe, nom):

    if len(groupe) == 0:
        return

    win_rate = (groupe["PnL_Pct"] > 0).mean()
    avg_pnl = groupe["PnL_Pct"].mean()

    print(
        f"{nom:25s} | "
        f"{len(groupe):4d} trades | "
        f"Win: {win_rate * 100:5.1f}% | "
        f"PnL moyen: {avg_pnl * 100:+.3f}%"
    )


# ============================================================
# 1. TAILLE DE LA CHUTE
# ============================================================

print("\n" + "=" * 70)
print("1. TAILLE DE LA CHUTE")
print("=" * 70)

analyse(df[(df["Signal_Drop"] >= -0.025)], "-2% à -2.5%")
analyse(df[(df["Signal_Drop"] < -0.025) &
           (df["Signal_Drop"] >= -0.03)], "-2.5% à -3%")
analyse(df[(df["Signal_Drop"] < -0.03) &
           (df["Signal_Drop"] >= -0.04)], "-3% à -4%")
analyse(df[df["Signal_Drop"] < -0.04], "< -4%")


# ============================================================
# 2. CHUTE PAR RAPPORT À L'ATR
# ============================================================

print("\n" + "=" * 70)
print("2. CHUTE / ATR")
print("=" * 70)

analyse(df[df["Drop_ATR_Ratio"] < 0.5], "< 0.5 ATR")
analyse(df[(df["Drop_ATR_Ratio"] >= 0.5) &
           (df["Drop_ATR_Ratio"] < 1)], "0.5 - 1 ATR")
analyse(df[(df["Drop_ATR_Ratio"] >= 1) &
           (df["Drop_ATR_Ratio"] < 1.5)], "1 - 1.5 ATR")
analyse(df[(df["Drop_ATR_Ratio"] >= 1.5) &
           (df["Drop_ATR_Ratio"] < 2)], "1.5 - 2 ATR")
analyse(df[df["Drop_ATR_Ratio"] >= 2], "> 2 ATR")


# ============================================================
# 3. VOLUME
# ============================================================

print("\n" + "=" * 70)
print("3. VOLUME")
print("=" * 70)

analyse(df[(df["Volume_Ratio"] >= 1) &
           (df["Volume_Ratio"] < 1.25)], "1 - 1.25x")
analyse(df[(df["Volume_Ratio"] >= 1.25) &
           (df["Volume_Ratio"] < 1.5)], "1.25 - 1.5x")
analyse(df[(df["Volume_Ratio"] >= 1.5) &
           (df["Volume_Ratio"] < 2)], "1.5 - 2x")
analyse(df[df["Volume_Ratio"] >= 2], "> 2x")


# ============================================================
# 4. DISTANCE SMA50
# ============================================================

print("\n" + "=" * 70)
print("4. DISTANCE PAR RAPPORT À SMA50")
print("=" * 70)

analyse(df[df["Distance_SMA50"] < 0.02], "< 2%")
analyse(df[(df["Distance_SMA50"] >= 0.02) &
           (df["Distance_SMA50"] < 0.05)], "2 - 5%")
analyse(df[(df["Distance_SMA50"] >= 0.05) &
           (df["Distance_SMA50"] < 0.10)], "5 - 10%")
analyse(df[(df["Distance_SMA50"] >= 0.10) &
           (df["Distance_SMA50"] < 0.20)], "10 - 20%")
analyse(df[df["Distance_SMA50"] >= 0.20], "> 20%")


# ============================================================
# 5. GAGNANTS VS PERDANTS
# ============================================================

print("\n" + "=" * 70)
print("5. GAGNANTS VS PERDANTS")
print("=" * 70)

winners = df[df["PnL_Pct"] > 0]
losers = df[df["PnL_Pct"] < 0]

print(f"\nGagnants : {len(winners)}")
print(f"Perdants : {len(losers)}")

variables = [
    "Signal_Drop",
    "ATR_Pct",
    "Drop_ATR_Ratio",
    "Volume_Ratio",
    "Distance_SMA50"
]

for col in variables:

    win_mean = winners[col].mean()
    loss_mean = losers[col].mean()
    difference = win_mean - loss_mean

    print(
        f"{col:20s} | "
        f"Gagnants: {win_mean:+.4f} | "
        f"Perdants: {loss_mean:+.4f} | "
        f"Diff: {difference:+.4f}"
    )


# ============================================================
# 6. TYPES DE SORTIE
# ============================================================

print("\n" + "=" * 70)
print("6. TYPES DE SORTIE")
print("=" * 70)

for reason in ["TP", "SL", "TIME", "FINAL"]:

    analyse(
        df[df["Exit_Reason"] == reason],
        reason
    )


# ============================================================
# 7. PAR ACTION
# ============================================================

print("\n" + "=" * 70)
print("7. PAR ACTION")
print("=" * 70)

stock_stats = (
    df.groupby("Ticker")["PnL_Pct"]
    .agg(["count", "mean"])
    .sort_values("mean", ascending=False)
)

for ticker, row in stock_stats.iterrows():

    print(
        f"{ticker:5s} | "
        f"{int(row['count']):3d} trades | "
        f"PnL moyen: {row['mean'] * 100:+.3f}%"
    )


# ============================================================
# 8. TEST DE ROBUSTESSE
# ============================================================

print("\n" + "=" * 70)
print("8. ROBUSTESSE : ON RETIRE LES MEILLEURS TRADES")
print("=" * 70)

df_sorted = df.sort_values(
    "PnL_Pct",
    ascending=False
).reset_index(drop=True)

for percentage in [0.01, 0.05, 0.10]:

    number_to_remove = max(
        1,
        int(len(df_sorted) * percentage)
    )

    remaining = df_sorted.iloc[number_to_remove:]

    analyse(
        remaining,
        f"Sans top {percentage * 100:.0f}%"
    )


# ============================================================
# 9. COMBINAISONS INTÉRESSANTES
# ============================================================

print("\n" + "=" * 70)
print("9. QUELQUES COMBINAISONS")
print("=" * 70)

conditions = {

    "Chute < 3% + Volume >= 1.25x":
        (df["Signal_Drop"] >= -0.03) &
        (df["Volume_Ratio"] >= 1.25),

    "Chute < 3% + Drop/ATR < 1.5":
        (df["Signal_Drop"] >= -0.03) &
        (df["Drop_ATR_Ratio"] < 1.5),

    "Volume 1.25-2x + Drop/ATR < 1.5":
        (df["Volume_Ratio"] >= 1.25) &
        (df["Volume_Ratio"] < 2) &
        (df["Drop_ATR_Ratio"] < 1.5),

    "SMA > 5% + Volume >= 1.25x":
        (df["Distance_SMA50"] >= 0.05) &
        (df["Volume_Ratio"] >= 1.25),

}

for name, condition in conditions.items():

    analyse(
        df[condition],
        name
    )


print("\n" + "=" * 70)
print("FIN DE L'AUTOPSIE")
print("=" * 70)