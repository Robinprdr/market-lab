import pandas as pd
import numpy as np

INPUT_FILE = "results/short_momentum/short_momentum_v1_research.csv"

df = pd.read_csv(INPUT_FILE)

# ---------------------------------------------------------
# Nettoyage
# ---------------------------------------------------------

df["Date"] = pd.to_datetime(df["Date"])

print("=" * 80)
print("SHORT MOMENTUM V1 — TEST DE FALSIFICATION")
print("=" * 80)

print(f"Rows : {len(df):,}")
print(f"Stocks : {df['Ticker'].nunique()}")
print(f"Dates : {df['Date'].min().date()} -> {df['Date'].max().date()}")

# ---------------------------------------------------------
# Seuils exploratoires
#
# IMPORTANT :
# Ce ne sont PAS encore des paramètres de stratégie.
# Ils servent uniquement à tester différentes formes
# raisonnables de momentum baissier.
# ---------------------------------------------------------

q20_r1 = df["Return_1D"].quantile(0.20)
q40_r1 = df["Return_1D"].quantile(0.40)

q20_r3 = df["Return_3D"].quantile(0.20)
q40_r3 = df["Return_3D"].quantile(0.40)

q20_r5 = df["Return_5D"].quantile(0.20)
q40_r5 = df["Return_5D"].quantile(0.40)

q80_atr = df["ATR_Pct"].quantile(0.80)
q80_volume = df["Volume_Ratio"].quantile(0.80)

q20_spy = df["SPY_Return_10D"].quantile(0.20)

print("\nSeuils exploratoires :")
print(f"Return_1D Q20 : {q20_r1:.3%}")
print(f"Return_1D Q40 : {q40_r1:.3%}")
print(f"Return_3D Q20 : {q20_r3:.3%}")
print(f"Return_3D Q40 : {q40_r3:.3%}")
print(f"Return_5D Q20 : {q20_r5:.3%}")
print(f"Return_5D Q40 : {q40_r5:.3%}")
print(f"ATR_Pct Q80 : {q80_atr:.3%}")
print(f"Volume_Ratio Q80 : {q80_volume:.2f}")
print(f"SPY_Return_10D Q20 : {q20_spy:.3%}")


# ---------------------------------------------------------
# Fonction d'analyse
#
# Convention :
# Future_Return négatif = favorable au SHORT
# ---------------------------------------------------------

def analyse(name, mask):

    sub = df.loc[mask].copy()

    print("\n" + "-" * 80)
    print(name)
    print("-" * 80)

    print(f"Observations : {len(sub):,}")

    if len(sub) == 0:
        print("Aucune observation.")
        return

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        mean = sub[col].mean()
        median = sub[col].median()

        # Pour un SHORT :
        # stock en baisse = gain
        short_win_rate = (sub[col] < 0).mean()

        print(
            f"{horizon}D : "
            f"moyenne {mean:+.3%} | "
            f"médiane {median:+.3%} | "
            f"WR short {short_win_rate:.1%}"
        )


# ---------------------------------------------------------
# BASELINE
# ---------------------------------------------------------

analyse(
    "BASELINE — toutes les observations",
    pd.Series(True, index=df.index)
)


# =========================================================
# 1. BAISSE MODÉRÉE
#
# On cherche précisément la zone où l'action baisse,
# mais n'est PAS encore dans une chute extrême.
# =========================================================

analyse(
    "1 — Return 1D modérément négatif (Q20 -> Q40)",
    (df["Return_1D"] >= q20_r1)
    & (df["Return_1D"] < q40_r1)
    & (df["Return_1D"] < 0)
)

analyse(
    "2 — Return 3D modérément négatif (Q20 -> Q40)",
    (df["Return_3D"] >= q20_r3)
    & (df["Return_3D"] < q40_r3)
    & (df["Return_3D"] < 0)
)

analyse(
    "3 — Return 5D modérément négatif (Q20 -> Q40)",
    (df["Return_5D"] >= q20_r5)
    & (df["Return_5D"] < q40_r5)
    & (df["Return_5D"] < 0)
)


# =========================================================
# 2. BAISSE EXTRÊME
#
# Contrôle important :
# si les fortes baisses rebondissent, cela expliquerait
# pourquoi "shorter après une grosse chute" fonctionne mal.
# =========================================================

analyse(
    "4 — Return 1D très négatif (Q20)",
    df["Return_1D"] <= q20_r1
)

analyse(
    "5 — Return 3D très négatif (Q20)",
    df["Return_3D"] <= q20_r3
)

analyse(
    "6 — Return 5D très négatif (Q20)",
    df["Return_5D"] <= q20_r5
)


# =========================================================
# 3. SÉQUENCE DE BAISSE
#
# On teste exactement ton intuition :
# plusieurs jours de baisse consécutifs.
# =========================================================

analyse(
    "7 — Exactement 2 jours consécutifs de baisse",
    df["Consecutive_Down_Days"] == 2
)

analyse(
    "8 — Exactement 3 jours consécutifs de baisse",
    df["Consecutive_Down_Days"] == 3
)

analyse(
    "9 — 2 à 3 jours consécutifs de baisse",
    df["Consecutive_Down_Days"].between(2, 3)
)


# =========================================================
# 4. BAISSE MODÉRÉE + VOLATILITÉ
#
# Pas simplement "grosse chute".
# On cherche une action qui commence à faiblir
# dans un environnement où les mouvements sont importants.
# =========================================================

analyse(
    "10 — Baisse 3D modérée + ATR élevé",
    (df["Return_3D"] >= q20_r3)
    & (df["Return_3D"] < q40_r3)
    & (df["Return_3D"] < 0)
    & (df["ATR_Pct"] >= q80_atr)
)


# =========================================================
# 5. BAISSE + VOLUME
#
# Confirmation par activité importante.
# =========================================================

analyse(
    "11 — Baisse 3D modérée + volume élevé",
    (df["Return_3D"] >= q20_r3)
    & (df["Return_3D"] < q40_r3)
    & (df["Return_3D"] < 0)
    & (df["Volume_Ratio"] >= q80_volume)
)


# =========================================================
# 6. BAISSE + MARCHÉ FAIBLE
#
# Une action faible dans un marché lui-même faible.
# =========================================================

analyse(
    "12 — Baisse 3D modérée + SPY faible",
    (df["Return_3D"] >= q20_r3)
    & (df["Return_3D"] < q40_r3)
    & (df["Return_3D"] < 0)
    & (df["SPY_Return_10D"] <= q20_spy)
)


# =========================================================
# 7. BAISSE + VOLUME + MARCHÉ FAIBLE
# =========================================================

analyse(
    "13 — Baisse 3D modérée + volume élevé + SPY faible",
    (df["Return_3D"] >= q20_r3)
    & (df["Return_3D"] < q40_r3)
    & (df["Return_3D"] < 0)
    & (df["Volume_Ratio"] >= q80_volume)
    & (df["SPY_Return_10D"] <= q20_spy)
)


# =========================================================
# 8. SÉQUENCE 2-3 JOURS + VOLUME
# =========================================================

analyse(
    "14 — 2-3 jours rouges + volume élevé",
    df["Consecutive_Down_Days"].between(2, 3)
    & (df["Volume_Ratio"] >= q80_volume)
)


# =========================================================
# 9. SÉQUENCE 2-3 JOURS + MARCHÉ FAIBLE
# =========================================================

analyse(
    "15 — 2-3 jours rouges + SPY faible",
    df["Consecutive_Down_Days"].between(2, 3)
    & (df["SPY_Return_10D"] <= q20_spy)
)


print("\n" + "=" * 80)
print("FIN DU TEST DE FALSIFICATION")
print("=" * 80)

print("""
INTERPRÉTATION :

Pour un SHORT :

Future_Return < 0  = favorable
Future_Return > 0  = défavorable

On ne cherche PAS le meilleur chiffre absolu.

On cherche une structure cohérente :

- moyenne négative
- médiane idéalement négative
- win rate SHORT > 50%
- résultat présent sur 3D et/ou 5D
- suffisamment d'observations

Si toutes les configurations restent positives,
cela signifie que "l'action baisse déjà" n'est probablement
PAS une bonne hypothèse de Short Momentum.

Dans ce cas, nous chercherons une autre logique bearish,
par exemple un échec de momentum / exhaustion,
plutôt que de forcer une stratégie.
""")
