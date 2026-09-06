import pandas as pd
import numpy as np


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "trades_autopsy.csv"

TRAIN_START = "2018-01-01"
TEST_START = "2023-01-01"
TEST_END = "2026-01-01"


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(df["Date"])

# On garde uniquement les données utiles
df = df[
    (df["Date"] >= TRAIN_START) &
    (df["Date"] < TEST_END)
].copy()


# ============================================================
# SÉPARATION TRAIN / TEST
# ============================================================

train = df[
    (df["Date"] >= TRAIN_START) &
    (df["Date"] < TEST_START)
].copy()

test = df[
    (df["Date"] >= TEST_START) &
    (df["Date"] < TEST_END)
].copy()


# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse(data, nom):
    if len(data) == 0:
        print(f"{nom}: aucun trade")
        return

    win_rate = (data["PnL_Pct"] > 0).mean() * 100
    avg_pnl = data["PnL_Pct"].mean() * 100

    total_pnl = data["PnL_Pct"].sum() * 100

    winners = data[data["PnL_Pct"] > 0]["PnL_Pct"]
    losers = data[data["PnL_Pct"] <= 0]["PnL_Pct"]

    avg_win = winners.mean() * 100 if len(winners) else 0
    avg_loss = losers.mean() * 100 if len(losers) else 0

    print(
        f"{nom:<45} | "
        f"{len(data):>4} trades | "
        f"Win {win_rate:>5.1f}% | "
        f"Avg {avg_pnl:>7.3f}% | "
        f"Somme {total_pnl:>8.2f}%"
    )


# ============================================================
# HEADER
# ============================================================

print("\n" + "=" * 105)
print("ROBUSTESSE OOS")
print("=" * 105)

print("\nTRAIN")
print("-" * 105)

analyse(train, "BASE TRAIN")

train_filtered = train[train["Signal_Drop"] >= -0.04].copy()

analyse(
    train_filtered,
    "BASE + exclut chute >4%"
)


print("\nTEST")
print("-" * 105)

analyse(test, "BASE TEST")

test_filtered = test[test["Signal_Drop"] >= -0.04].copy()

analyse(
    test_filtered,
    "BASE + exclut chute >4%"
)


# ============================================================
# RETRAIT DES MEILLEURS TRADES
# ============================================================

print("\n" + "=" * 105)
print("ROBUSTESSE : ON RETIRE LES MEILLEURS TRADES")
print("=" * 105)


# Notre stratégie candidate
strategy = test_filtered.copy()

analyse(strategy, "STRATEGIE COMPLETE")


# ------------------------------------------------------------
# Retire les meilleurs X% des trades
# ------------------------------------------------------------

for pct in [1, 5, 10, 20]:

    n_remove = int(len(strategy) * pct / 100)

    if n_remove < 1:
        continue

    # On classe les trades du meilleur au pire
    sorted_trades = strategy.sort_values(
        "PnL_Pct",
        ascending=False
    )

    # On retire les meilleurs trades
    remaining = sorted_trades.iloc[n_remove:].copy()

    analyse(
        remaining,
        f"Après retrait des meilleurs {pct}%"
    )


# ============================================================
# ANALYSE PAR ANNÉE
# ============================================================

print("\n" + "=" * 105)
print("ANALYSE PAR ANNÉE — TEST")
print("=" * 105)

strategy["Year"] = strategy["Date"].dt.year

for year, group in strategy.groupby("Year"):

    analyse(
        group,
        f"Année {year}"
    )


# ============================================================
# ANALYSE PAR ANNÉE AVEC EXCLUSION >4%
# ============================================================

print("\n" + "=" * 105)
print("ANALYSE PAR ANNÉE — STRATÉGIE >4% EXCLUE")
print("=" * 105)

for year, group in strategy.groupby("Year"):

    print(
        f"{year} : "
        f"{len(group)} trades | "
        f"Win {(group['PnL_Pct'] > 0).mean() * 100:.1f}% | "
        f"Avg {group['PnL_Pct'].mean() * 100:.3f}%"
    )


# ============================================================
# CONCENTRATION DES PROFITS
# ============================================================

print("\n" + "=" * 105)
print("CONCENTRATION DES PROFITS")
print("=" * 105)

profits = strategy["PnL_Pct"].sort_values(ascending=False)

total_positive = profits[profits > 0].sum()

for pct in [1, 5, 10]:

    n = max(1, int(len(profits) * pct / 100))

    top_profits = profits.head(n).sum()

    if total_positive != 0:
        contribution = top_profits / total_positive * 100
    else:
        contribution = 0

    print(
        f"Top {pct:>2}% des trades gagnants = "
        f"{contribution:>6.2f}% des profits gagnants"
    )


# ============================================================
# CONCLUSION AUTOMATIQUE
# ============================================================

print("\n" + "=" * 105)
print("FIN DU TEST")
print("=" * 105)

print("""
Ce test ne cherche PAS à améliorer artificiellement la stratégie.

Il cherche à répondre à une question :

    "Est-ce que notre avantage existe encore
     si quelques trades exceptionnels sont retirés ?"

Si les résultats restent positifs après retrait des meilleurs
trades, c'est un signe que l'avantage est plus largement réparti.

Si les résultats s'effondrent immédiatement, cela signifie que
notre performance dépend peut-être de quelques trades chanceux.

ATTENTION :
ce test ne prouve toujours pas que la stratégie fonctionnera
dans le futur. Il sert uniquement à mesurer sa robustesse
sur notre période TEST.
""")