import pandas as pd
import numpy as np

INPUT_FILE = "results/short_momentum/short_momentum_v1_research.csv"
OUTPUT_FILE = "results/short_momentum/short_momentum_v2_research.csv"

df = pd.read_csv(INPUT_FILE)
df["Date"] = pd.to_datetime(df["Date"])

print("=" * 90)
print("SHORT MOMENTUM V2 — ACCÉLÉRATION BAISSIÈRE")
print("=" * 90)

print(f"Rows : {len(df):,}")
print(f"Stocks : {df['Ticker'].nunique()}")
print(f"Dates : {df['Date'].min().date()} -> {df['Date'].max().date()}")

# =========================================================
# NOUVELLES VARIABLES
# =========================================================

# Accélération baissière :
#
# Exemple :
# 10 derniers jours : -3%
# 3 derniers jours  : -2%
#
# Le mouvement récent est plus violent que le mouvement
# précédent.
#
# Plus la valeur est négative, plus l'accélération est forte.

df["Bearish_Acceleration_3v10"] = (
    df["Return_3D"] - (df["Return_10D"] * 3 / 10)
)

df["Bearish_Acceleration_5v20"] = (
    df["Return_5D"] - (df["Return_20D"] * 5 / 20)
)

# Accélération simple entre court terme et moyen terme
df["Bearish_Acceleration_1v5"] = (
    df["Return_1D"] - (df["Return_5D"] / 5)
)

# Distance à SMA50 déjà disponible dans V1.
# On ajoute une mesure de tendance :
# pente approximative SMA20 vs SMA50.

df["Trend_Bearish"] = (
    df["SMA20_vs_SMA50"] < 0
)

# Prix sous SMA50
df["Below_SMA50"] = (
    df["Distance_SMA50"] < 0
)

# Prix sous SMA200
df["Below_SMA200"] = (
    df["Distance_SMA200"] < 0
)


# =========================================================
# SEUILS
# =========================================================

def quantile(col, q):
    return df[col].quantile(q)


# Accélérations
acc_3v10_q20 = quantile("Bearish_Acceleration_3v10", 0.20)
acc_3v10_q30 = quantile("Bearish_Acceleration_3v10", 0.30)
acc_3v10_q40 = quantile("Bearish_Acceleration_3v10", 0.40)

acc_5v20_q20 = quantile("Bearish_Acceleration_5v20", 0.20)
acc_5v20_q30 = quantile("Bearish_Acceleration_5v20", 0.30)

acc_1v5_q20 = quantile("Bearish_Acceleration_1v5", 0.20)
acc_1v5_q30 = quantile("Bearish_Acceleration_1v5", 0.30)

# Rendements
r3_q40 = quantile("Return_3D", 0.40)
r3_q60 = quantile("Return_3D", 0.60)

r5_q40 = quantile("Return_5D", 0.40)
r5_q60 = quantile("Return_5D", 0.60)

r10_q40 = quantile("Return_10D", 0.40)

# ATR / volume
atr_q60 = quantile("ATR_Pct", 0.60)
atr_q80 = quantile("ATR_Pct", 0.80)

volume_q60 = quantile("Volume_Ratio", 0.60)
volume_q80 = quantile("Volume_Ratio", 0.80)

# SPY
spy_q40 = quantile("SPY_Return_10D", 0.40)


print("\nSEUILS EXPLORATOIRES")
print("-" * 90)

print(f"Acceleration 3v10 Q20 : {acc_3v10_q20:+.3%}")
print(f"Acceleration 3v10 Q30 : {acc_3v10_q30:+.3%}")
print(f"Acceleration 3v10 Q40 : {acc_3v10_q40:+.3%}")

print(f"Acceleration 5v20 Q20 : {acc_5v20_q20:+.3%}")
print(f"Acceleration 5v20 Q30 : {acc_5v20_q30:+.3%}")

print(f"Acceleration 1v5 Q20 : {acc_1v5_q20:+.3%}")
print(f"Acceleration 1v5 Q30 : {acc_1v5_q30:+.3%}")

print(f"Return 3D Q40 : {r3_q40:+.3%}")
print(f"Return 3D Q60 : {r3_q60:+.3%}")

print(f"Return 5D Q40 : {r5_q40:+.3%}")
print(f"Return 5D Q60 : {r5_q60:+.3%}")

print(f"ATR Q60 : {atr_q60:.3%}")
print(f"ATR Q80 : {atr_q80:.3%}")

print(f"Volume Q60 : {volume_q60:.2f}")
print(f"Volume Q80 : {volume_q80:.2f}")

print(f"SPY Return10 Q40 : {spy_q40:+.3%}")


# =========================================================
# ANALYSE
# =========================================================

results = []


def analyse(name, mask):

    sub = df.loc[mask].copy()

    print("\n" + "-" * 90)
    print(name)
    print("-" * 90)

    n = len(sub)

    print(f"Observations : {n:,}")

    if n == 0:
        return

    for horizon in [1, 3, 5]:

        col = f"Future_Return_{horizon}D"

        mean = sub[col].mean()
        median = sub[col].median()

        # SHORT :
        # rendement action négatif = gain
        short_wr = (sub[col] < 0).mean()

        print(
            f"{horizon}D : "
            f"moyenne {mean:+.3%} | "
            f"médiane {median:+.3%} | "
            f"WR short {short_wr:.1%}"
        )

        results.append({
            "Hypothesis": name,
            "Observations": n,
            "Horizon": horizon,
            "Mean": mean,
            "Median": median,
            "Short_Win_Rate": short_wr,
        })


# =========================================================
# BASELINE
# =========================================================

analyse(
    "BASELINE",
    pd.Series(True, index=df.index)
)


# =========================================================
# HYPOTHÈSE 1
#
# Accélération récente :
# 3 jours deviennent plus faibles que le rythme des 10 jours.
# =========================================================

analyse(
    "1 — Accélération baissière 3v10 Q20",
    df["Bearish_Acceleration_3v10"] <= acc_3v10_q20
)


# =========================================================
# HYPOTHÈSE 2
#
# Accélération modérée :
# éviter les mouvements extrêmes.
# =========================================================

analyse(
    "2 — Accélération 3v10 Q20-Q40",
    (df["Bearish_Acceleration_3v10"] > acc_3v10_q20)
    & (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
)


# =========================================================
# HYPOTHÈSE 3
#
# Accélération + tendance baissière.
# =========================================================

analyse(
    "3 — Accélération 3v10 + sous SMA50",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & df["Below_SMA50"]
)


# =========================================================
# HYPOTHÈSE 4
#
# Accélération + tendance sous SMA50 + sous SMA200.
# =========================================================

analyse(
    "4 — Accélération + sous SMA50 + sous SMA200",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & df["Below_SMA50"]
    & df["Below_SMA200"]
)


# =========================================================
# HYPOTHÈSE 5
#
# Accélération + baisse récente modérée.
#
# L'idée :
# l'action commence à accélérer mais n'a pas encore
# subi une énorme chute.
# =========================================================

analyse(
    "5 — Accélération + baisse 3D modérée",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & (df["Return_3D"] >= df["Return_3D"].quantile(0.20))
    & (df["Return_3D"] <= r3_q60)
)


# =========================================================
# HYPOTHÈSE 6
#
# Accélération 5 jours vs 20 jours.
# =========================================================

analyse(
    "6 — Accélération baissière 5v20 Q20",
    df["Bearish_Acceleration_5v20"] <= acc_5v20_q20
)


# =========================================================
# HYPOTHÈSE 7
#
# Accélération 5v20 modérée.
# =========================================================

analyse(
    "7 — Accélération 5v20 Q20-Q30",
    (df["Bearish_Acceleration_5v20"] > acc_5v20_q20)
    & (df["Bearish_Acceleration_5v20"] <= acc_5v20_q30)
)


# =========================================================
# HYPOTHÈSE 8
#
# Accélération quotidienne :
# le dernier jour est particulièrement faible
# par rapport aux 5 derniers jours.
# =========================================================

analyse(
    "8 — Accélération 1v5 Q20",
    df["Bearish_Acceleration_1v5"] <= acc_1v5_q20
)


# =========================================================
# HYPOTHÈSE 9
#
# Accélération + volume élevé.
#
# Ici volume élevé = confirmation potentielle,
# pas volume faible comme dans notre test précédent.
# =========================================================

analyse(
    "9 — Accélération 3v10 + volume élevé",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & (df["Volume_Ratio"] >= volume_q80)
)


# =========================================================
# HYPOTHÈSE 10
#
# Accélération + ATR élevé.
#
# Mais sans imposer une grosse baisse préalable.
# =========================================================

analyse(
    "10 — Accélération 3v10 + ATR élevé",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & (df["ATR_Pct"] >= atr_q80)
)


# =========================================================
# HYPOTHÈSE 11
#
# Accélération + volume élevé + tendance baissière.
# =========================================================

analyse(
    "11 — Accélération + volume + sous SMA50",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & (df["Volume_Ratio"] >= volume_q80)
    & df["Below_SMA50"]
)


# =========================================================
# HYPOTHÈSE 12
#
# Accélération + marché faible.
# =========================================================

analyse(
    "12 — Accélération + SPY faible",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & (df["SPY_Return_10D"] <= spy_q40)
)


# =========================================================
# HYPOTHÈSE 13
#
# Accélération + tendance + volume.
# =========================================================

analyse(
    "13 — Accélération + sous SMA50 + volume élevé",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & df["Below_SMA50"]
    & (df["Volume_Ratio"] >= volume_q80)
)


# =========================================================
# HYPOTHÈSE 14
#
# Accélération + sous SMA50 + marché faible.
# =========================================================

analyse(
    "14 — Accélération + sous SMA50 + SPY faible",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & df["Below_SMA50"]
    & (df["SPY_Return_10D"] <= spy_q40)
)


# =========================================================
# HYPOTHÈSE 15
#
# Configuration complète mais volontairement simple :
#
# accélération
# + tendance baissière
# + volume
#
# Pas d'ATR obligatoire.
# =========================================================

analyse(
    "15 — Accélération + tendance + volume",
    (df["Bearish_Acceleration_3v10"] <= acc_3v10_q40)
    & df["Below_SMA50"]
    & (df["Volume_Ratio"] >= volume_q80)
)


# =========================================================
# SAUVEGARDE
# =========================================================

results_df = pd.DataFrame(results)

results_df.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\n" + "=" * 90)
print("FIN SHORT MOMENTUM V2")
print("=" * 90)

print(f"Résultats sauvegardés : {OUTPUT_FILE}")

print("""
IMPORTANT :

Ce test est EXPLORATOIRE.

Nous n'avons pas encore sélectionné de stratégie finale.

Pour un SHORT :

Future_Return < 0 = favorable
Future_Return > 0 = défavorable

Ce que nous cherchons :

1. moyenne négative
2. médiane idéalement négative
3. win rate SHORT > 50%
4. effet présent sur 3D et/ou 5D
5. suffisamment d'observations

Si une hypothèse semble intéressante ici,
nous NE l'optimiserons pas immédiatement.

Nous la testerons ensuite en :
TRAIN / TEST
puis WALK-FORWARD.

Le but est de vérifier que l'accélération baissière
est réellement prédictive et pas seulement intéressante
sur l'ensemble historique.
""")
