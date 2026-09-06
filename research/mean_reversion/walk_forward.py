import pandas as pd
import numpy as np


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "results/mean_reversion/trades_autopsy.csv"

START_DATE = "2018-01-01"
END_DATE = "2025-12-20"


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(df["Date"])

df = df[
    (df["Date"] >= START_DATE) &
    (df["Date"] < END_DATE)
].copy()


# ============================================================
# STRATÉGIE
# ============================================================

# Notre règle actuelle :
# On exclut les trades lorsque la chute précédente
# est supérieure à 4%.

df["Strategy"] = df["Signal_Drop"] >= -0.04


# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse(data, label):

    if len(data) == 0:
        print(f"{label:<45} | aucun trade")
        return

    win_rate = (data["PnL_Pct"] > 0).mean() * 100
    avg_pnl = data["PnL_Pct"].mean() * 100
    total_pnl = data["PnL_Pct"].sum() * 100

    print(
        f"{label:<45} | "
        f"{len(data):>4} trades | "
        f"Win {win_rate:>5.1f}% | "
        f"Avg {avg_pnl:>7.3f}% | "
        f"Somme {total_pnl:>8.2f}%"
    )


# ============================================================
# WALK-FORWARD
# ============================================================

# Chaque période de test est totalement séparée.
#
# Exemple :
#
# TRAIN : 2018-2020
# TEST  : 2021
#
# TRAIN : 2019-2021
# TEST  : 2022
#
# etc.


periods = [
    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("2022-01-01", "2025-01-01", "2025-01-01", "2025-12-20"),
]


print("\n" + "=" * 115)
print("WALK-FORWARD TEST")
print("=" * 115)

print("""
Principe :

TRAIN = période historique disponible avant le test
TEST  = période future jamais utilisée pour mesurer la stratégie

La stratégie testée est :

    Signal_Drop >= -4%

Autrement dit :
    on évite les chutes supérieures à 4%.

IMPORTANT :
Nous ne modifions aucun paramètre pendant ce test.
""")


# ============================================================
# RÉSULTATS
# ============================================================

all_test_trades = []


for i, (train_start, train_end, test_start, test_end) in enumerate(periods, 1):

    train = df[
        (df["Date"] >= train_start) &
        (df["Date"] < train_end)
    ].copy()

    test = df[
        (df["Date"] >= test_start) &
        (df["Date"] < test_end)
    ].copy()

    train_strategy = train[train["Strategy"]].copy()
    test_strategy = test[test["Strategy"]].copy()

    print("\n" + "-" * 115)

    print(
        f"WINDOW {i} | "
        f"TRAIN {train_start[:4]}-{train_end[:4]} "
        f"→ TEST {test_start[:4]}-{test_end[:4]}"
    )

    print("-" * 115)

    analyse(
        train_strategy,
        "TRAIN"
    )

    analyse(
        test_strategy,
        "TEST"
    )

    if len(test_strategy) > 0:
        all_test_trades.append(test_strategy)


# ============================================================
# RÉSULTAT GLOBAL DES TESTS
# ============================================================

print("\n" + "=" * 115)
print("RÉSULTAT GLOBAL DES PÉRIODES TEST")
print("=" * 115)

if all_test_trades:

    combined_test = pd.concat(
        all_test_trades,
        ignore_index=True
    )

    analyse(
        combined_test,
        "TOUS LES TESTS COMBINÉS"
    )

    positive_periods = 0

    print("\nDétail des périodes :")

    for i, (train_start, train_end, test_start, test_end) in enumerate(periods, 1):

        test = df[
            (df["Date"] >= test_start) &
            (df["Date"] < test_end) &
            (df["Strategy"])
        ].copy()

        if len(test) > 0:

            avg = test["PnL_Pct"].mean() * 100

            if avg > 0:
                positive_periods += 1

            print(
                f"TEST {i} ({test_start[:4]} → {test_end[:4]}) : "
                f"{len(test)} trades | "
                f"Avg {avg:.3f}%"
            )

    print(
        f"\nPériodes positives : "
        f"{positive_periods}/{len(periods)}"
    )


# ============================================================
# COMPARAISON AVEC LE BASELINE
# ============================================================

print("\n" + "=" * 115)
print("COMPARAISON AVEC LE BASELINE")
print("=" * 115)

print("""
Nous comparons maintenant :

BASELINE :
    tous les trades

STRATÉGIE :
    exclusion des chutes >4%

Le but est de vérifier que l'amélioration
n'est pas uniquement apparente.
""")

for i, (train_start, train_end, test_start, test_end) in enumerate(periods, 1):

    test = df[
        (df["Date"] >= test_start) &
        (df["Date"] < test_end)
    ].copy()

    baseline = test.copy()

    strategy = test[
        test["Strategy"]
    ].copy()

    print(f"\nPériode TEST {test_start[:4]}")

    analyse(
        baseline,
        "Baseline"
    )

    analyse(
        strategy,
        "Stratégie >4% exclue"
    )


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 115)
print("FIN DU WALK-FORWARD")
print("=" * 115)

print("""
Ce test est une étape importante.

Nous cherchons surtout à voir :

1. Plusieurs périodes TEST positives
2. Une performance moyenne positive
3. Une amélioration par rapport au baseline
4. Une absence de dépendance à une seule année

Même si le résultat est positif, cela ne signifie PAS
que la stratégie est prête pour du trading réel.

Il faudra ensuite tester :
- coûts de transaction
- slippage
- capital réel
- position sizing basé sur le risque
- univers complet de titres
- périodes de marché différentes
- et idéalement des données intraday.
""")