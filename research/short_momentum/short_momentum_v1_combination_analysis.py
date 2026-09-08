import pandas as pd
import numpy as np

INPUT = "results/short_momentum/short_momentum_v1_research.csv"

df = pd.read_csv(INPUT, parse_dates=["Date"])

print("=" * 80)
print("SHORT MOMENTUM V1 — COMBINATION ANALYSIS CORRIGÉE")
print("=" * 80)

print(f"\nDataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")

# ============================================================
# Convention
# ============================================================
#
# Future_Return négatif = l'action baisse
# Pour un SHORT = bon
#
# On utilise donc les moyennes futures les PLUS NÉGATIVES.
# ============================================================


def stats(data, column):
    x = data[column].dropna()

    if len(x) == 0:
        return None

    return {
        "mean": x.mean(),
        "median": x.median(),
        "wr": (x < 0).mean(),
        "n": len(x),
    }


# ============================================================
# Seuils calculés sur l'ensemble uniquement pour exploration.
#
# IMPORTANT :
# Ces seuils ne seront PAS utilisés comme validation finale.
# Ils serviront uniquement à découvrir les combinaisons
# intéressantes avant OOS / walk-forward.
# ============================================================

thresholds = {
    "ATR_Q80": df["ATR_Pct"].quantile(0.80),
    "ATR_Q60": df["ATR_Pct"].quantile(0.60),

    "Return1D_Q20": df["Return_1D"].quantile(0.20),
    "Return3D_Q20": df["Return_3D"].quantile(0.20),
    "Return5D_Q20": df["Return_5D"].quantile(0.20),
    "Return20D_Q20": df["Return_20D"].quantile(0.20),

    "Volume_Q20": df["Volume_Ratio"].quantile(0.20),

    "NegativeDays10_Q80":
        df["Negative_Days_10"].quantile(0.80),

    "ConsecutiveDown_Q80":
        df["Consecutive_Down_Days"].quantile(0.80),

    "ReturnConsecutiveDown_Q20":
        df["Return_Consecutive_Down"].quantile(0.20),

    "SPY_Return10_Q20":
        df["SPY_Return_10D"].quantile(0.20),
}


print("\nSeuils exploratoires :")

for key, value in thresholds.items():
    print(f"{key:35s}: {value:.4f}")


# ============================================================
# Combinaisons
# ============================================================

conditions = {

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    "ATR élevé":
        df["ATR_Pct"] >= thresholds["ATR_Q80"],

    "ATR très élevé":
        df["ATR_Pct"] >= thresholds["ATR_Q60"],

    # --------------------------------------------------------
    # Direction récente
    # --------------------------------------------------------

    "Return 1D faible":
        df["Return_1D"] <= thresholds["Return1D_Q20"],

    "Return 3D faible":
        df["Return_3D"] <= thresholds["Return3D_Q20"],

    "Return 5D faible":
        df["Return_5D"] <= thresholds["Return5D_Q20"],

    "Return 20D faible":
        df["Return_20D"] <= thresholds["Return20D_Q20"],

    # --------------------------------------------------------
    # Activité
    # --------------------------------------------------------

    "Volume faible":
        df["Volume_Ratio"] <= thresholds["Volume_Q20"],

    "Nombre jours baisse élevé":
        df["Negative_Days_10"] >= thresholds["NegativeDays10_Q80"],

    # --------------------------------------------------------
    # Séquence de baisse
    # --------------------------------------------------------

    "Séquence baisse":
        df["Consecutive_Down_Days"] >=
        thresholds["ConsecutiveDown_Q80"],

    "Baisse séquentielle forte":
        df["Return_Consecutive_Down"] <=
        thresholds["ReturnConsecutiveDown_Q20"],

    # --------------------------------------------------------
    # Marché
    # --------------------------------------------------------

    "SPY faible":
        df["SPY_Return_10D"] <=
        thresholds["SPY_Return10_Q20"],
}


# ============================================================
# Affichage d'une condition
# ============================================================

def print_condition(name, mask):

    print(f"\n{name}")

    subset = df.loc[mask]

    print(f"n = {len(subset):,}")

    if len(subset) == 0:
        return

    for horizon in [1, 3, 5, 10]:

        col = f"Future_Return_{horizon}D"

        s = stats(subset, col)

        print(
            f"  {horizon:>2}D : "
            f"{s['mean']:+.3%} | "
            f"WR {s['wr']:.1%}"
        )


# ============================================================
# Conditions individuelles
# ============================================================

print("\n")
print("=" * 80)
print("CONDITIONS INDIVIDUELLES")
print("=" * 80)

for name, mask in conditions.items():
    print_condition(name, mask)


# ============================================================
# Combinaisons principales
# ============================================================

combinations = {

    "ATR + Return1D":
        conditions["ATR élevé"]
        & conditions["Return 1D faible"],

    "ATR + Return3D":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"],

    "ATR + Return5D":
        conditions["ATR élevé"]
        & conditions["Return 5D faible"],

    "ATR + Return20D":
        conditions["ATR élevé"]
        & conditions["Return 20D faible"],

    "ATR + Volume faible":
        conditions["ATR élevé"]
        & conditions["Volume faible"],

    "ATR + NegativeDays":
        conditions["ATR élevé"]
        & conditions["Nombre jours baisse élevé"],

    "ATR + Séquence baisse":
        conditions["ATR élevé"]
        & conditions["Séquence baisse"],

    "ATR + Baisse séquentielle":
        conditions["ATR élevé"]
        & conditions["Baisse séquentielle forte"],

    "ATR + SPY faible":
        conditions["ATR élevé"]
        & conditions["SPY faible"],

    # --------------------------------------------------------
    # Combinaisons directionnelles
    # --------------------------------------------------------

    "ATR + Return1D + Return3D":
        conditions["ATR élevé"]
        & conditions["Return 1D faible"]
        & conditions["Return 3D faible"],

    "ATR + Return3D + Return5D":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Return 5D faible"],

    "ATR + Return3D + Return20D":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Return 20D faible"],

    "ATR + Return1D + Return20D":
        conditions["ATR élevé"]
        & conditions["Return 1D faible"]
        & conditions["Return 20D faible"],

    # --------------------------------------------------------
    # Séquence + direction
    # --------------------------------------------------------

    "ATR + Return3D + NegativeDays":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Nombre jours baisse élevé"],

    "ATR + Return3D + Séquence":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Séquence baisse"],

    "ATR + Return3D + Baisse séquentielle":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Baisse séquentielle forte"],

    # --------------------------------------------------------
    # Marché
    # --------------------------------------------------------

    "ATR + Return3D + SPY faible":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["SPY faible"],

    "ATR + Return1D + SPY faible":
        conditions["ATR élevé"]
        & conditions["Return 1D faible"]
        & conditions["SPY faible"],

    # --------------------------------------------------------
    # Combinaison plus stricte
    # --------------------------------------------------------

    "ATR + Return1D + Return3D + Return20D":
        conditions["ATR élevé"]
        & conditions["Return 1D faible"]
        & conditions["Return 3D faible"]
        & conditions["Return 20D faible"],

    "ATR + Return3D + Return20D + SPY":
        conditions["ATR élevé"]
        & conditions["Return 3D faible"]
        & conditions["Return 20D faible"]
        & conditions["SPY faible"],
}


# ============================================================
# Résultats
# ============================================================

print("\n")
print("=" * 80)
print("COMBINAISONS")
print("=" * 80)

results = []

for name, mask in combinations.items():

    subset = df.loc[mask]

    row = {
        "name": name,
        "n": len(subset),
    }

    print(f"\n--- {name} ---")
    print(f"n = {len(subset):,}")

    if len(subset) == 0:
        continue

    for horizon in [1, 3, 5, 10]:

        col = f"Future_Return_{horizon}D"

        s = stats(subset, col)

        row[f"mean_{horizon}D"] = s["mean"]
        row[f"wr_{horizon}D"] = s["wr"]

        print(
            f"{horizon:>2}D : "
            f"mean {s['mean']:+.3%} | "
            f"WR {s['wr']:.1%}"
        )

    results.append(row)


# ============================================================
# Classement
#
# On privilégie ici les moyennes les plus négatives.
# Cela reste uniquement exploratoire.
# ============================================================

results_df = pd.DataFrame(results)

if not results_df.empty:

    print("\n")
    print("=" * 80)
    print("TOP COMBINAISONS — 3 JOURS")
    print("=" * 80)

    top3 = results_df.sort_values(
        "mean_3D"
    ).head(10)

    for _, row in top3.iterrows():

        print(
            f"{row['name']:45s} "
            f"{row['mean_3D']:+.3%} | "
            f"WR {row['wr_3D']:.1%} | "
            f"n={int(row['n']):,}"
        )

    print("\n")
    print("=" * 80)
    print("TOP COMBINAISONS — 5 JOURS")
    print("=" * 80)

    top5 = results_df.sort_values(
        "mean_5D"
    ).head(10)

    for _, row in top5.iterrows():

        print(
            f"{row['name']:45s} "
            f"{row['mean_5D']:+.3%} | "
            f"WR {row['wr_5D']:.1%} | "
            f"n={int(row['n']):,}"
        )

    print("\n")
    print("=" * 80)
    print("TOP COMBINAISONS — 10 JOURS")
    print("=" * 80)

    top10 = results_df.sort_values(
        "mean_10D"
    ).head(10)

    for _, row in top10.iterrows():

        print(
            f"{row['name']:45s} "
            f"{row['mean_10D']:+.3%} | "
            f"WR {row['wr_10D']:.1%} | "
            f"n={int(row['n']):,}"
        )


print("\n")
print("=" * 80)
print("FIN DE L'ANALYSE")
print("=" * 80)

print(
    "\nATTENTION : ces seuils sont exploratoires."
    "\nAucune combinaison n'est encore validée."
    "\nLa prochaine étape sera OOS + walk-forward."
)

