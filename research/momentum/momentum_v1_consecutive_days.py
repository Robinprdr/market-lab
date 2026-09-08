import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")
OUTPUT_FILE = Path("results/momentum/momentum_v1_consecutive_days.csv")

print("=" * 70)
print("MOMENTUM V1 - CONSECUTIVE DAYS ANALYSIS")
print("=" * 70)

# -------------------------------------------------------------------
# 1. Chargement
# -------------------------------------------------------------------

df = pd.read_csv(INPUT_FILE)

print(f"\nFichier chargé : {INPUT_FILE}")
print(f"Lignes : {len(df):,}")
print(f"Actions : {df['Ticker'].nunique()}")

# Vérification
required_columns = [
    "Ticker",
    "Date",
    "Close",
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]

missing = [c for c in required_columns if c not in df.columns]

if missing:
    raise ValueError(f"Colonnes manquantes : {missing}")

df["Date"] = pd.to_datetime(df["Date"])
df = df.sort_values(["Ticker", "Date"]).reset_index(drop=True)

# -------------------------------------------------------------------
# 2. Calcul des séries de jours consécutifs
# -------------------------------------------------------------------

print("\nCalcul des séries de jours consécutifs...")

def consecutive_up_days(group):
    returns = group["Close"].pct_change()

    result = []
    count = 0

    for r in returns:
        if pd.isna(r):
            count = 0
        elif r > 0:
            count += 1
        else:
            count = 0

        result.append(count)

    return pd.Series(result, index=group.index)


def consecutive_down_days(group):
    returns = group["Close"].pct_change()

    result = []
    count = 0

    for r in returns:
        if pd.isna(r):
            count = 0
        elif r < 0:
            count += 1
        else:
            count = 0

        result.append(count)

    return pd.Series(result, index=group.index)


df["Consecutive_Up_Days"] = (
    df.groupby("Ticker", group_keys=False)
      .apply(consecutive_up_days)
      .reset_index(level=0, drop=True)
)

df["Consecutive_Down_Days"] = (
    df.groupby("Ticker", group_keys=False)
      .apply(consecutive_down_days)
      .reset_index(level=0, drop=True)
)

# -------------------------------------------------------------------
# 3. Rendement cumulé pendant la série de hausse
# -------------------------------------------------------------------

def consecutive_up_return(group):
    returns = group["Close"].pct_change()

    result = []
    cumulative = 1.0

    for r in returns:
        if pd.isna(r):
            cumulative = 1.0
            result.append(np.nan)

        elif r > 0:
            cumulative *= (1 + r)
            result.append(cumulative - 1)

        else:
            cumulative = 1.0
            result.append(0.0)

    return pd.Series(result, index=group.index)


df["Return_Consecutive_Up"] = (
    df.groupby("Ticker", group_keys=False)
      .apply(consecutive_up_return)
      .reset_index(level=0, drop=True)
)

# -------------------------------------------------------------------
# 4. Nombre de jours positifs sur différentes fenêtres
# -------------------------------------------------------------------

returns = df.groupby("Ticker")["Close"].pct_change()

df["Up_Days_3"] = (
    returns.gt(0)
    .groupby(df["Ticker"])
    .transform(lambda x: x.rolling(3).sum())
)

df["Up_Days_5"] = (
    returns.gt(0)
    .groupby(df["Ticker"])
    .transform(lambda x: x.rolling(5).sum())
)

df["Up_Days_10"] = (
    returns.gt(0)
    .groupby(df["Ticker"])
    .transform(lambda x: x.rolling(10).sum())
)

# -------------------------------------------------------------------
# 5. Sauvegarde du dataset enrichi
# -------------------------------------------------------------------

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
df.to_csv(OUTPUT_FILE, index=False)

print(f"\n✓ Dataset enrichi sauvegardé : {OUTPUT_FILE}")

# -------------------------------------------------------------------
# 6. Analyse par nombre de jours consécutifs
# -------------------------------------------------------------------

print("\n")
print("=" * 70)
print("ANALYSE : CONSECUTIVE UP DAYS")
print("=" * 70)

horizons = [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]

# On limite volontairement à 1-5 jours consécutifs.
# Au-delà, les observations deviennent beaucoup plus rares.
for horizon in horizons:

    print(f"\n--- {horizon} ---")

    temp = df[
        ["Consecutive_Up_Days", horizon]
    ].dropna()

    for n in range(1, 6):

        subset = temp[temp["Consecutive_Up_Days"] == n]

        if len(subset) < 100:
            print(
                f"{n} jour(s) consécutif(s) : "
                f"échantillon trop faible ({len(subset)})"
            )
            continue

        avg_return = subset[horizon].mean() * 100
        win_rate = (subset[horizon] > 0).mean() * 100

        print(
            f"{n} jour(s) : "
            f"N={len(subset):,} | "
            f"Future={avg_return:+.3f}% | "
            f"WR={win_rate:.1f}%"
        )

    # Groupe >= 3 jours
    subset = temp[temp["Consecutive_Up_Days"] >= 3]

    if len(subset) >= 100:
        avg_return = subset[horizon].mean() * 100
        win_rate = (subset[horizon] > 0).mean() * 100

        print(
            f">=3 jours : "
            f"N={len(subset):,} | "
            f"Future={avg_return:+.3f}% | "
            f"WR={win_rate:.1f}%"
        )

# -------------------------------------------------------------------
# 7. Analyse du rendement de la série
# -------------------------------------------------------------------

print("\n")
print("=" * 70)
print("ANALYSE : RETURN CONSECUTIVE UP")
print("=" * 70)

temp = df[
    ["Return_Consecutive_Up", "Future_Return_1D",
     "Future_Return_3D", "Future_Return_5D"]
].dropna()

# Quantiles pour éviter de choisir arbitrairement un seuil
temp["Return_Consecutive_Up_Q"] = pd.qcut(
    temp["Return_Consecutive_Up"],
    q=5,
    labels=False,
    duplicates="drop"
) + 1

for horizon in [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
]:

    print(f"\n--- {horizon} ---")

    grouped = temp.groupby("Return_Consecutive_Up_Q")[horizon]

    for q, values in grouped:

        if len(values) == 0:
            continue

        avg_return = values.mean() * 100
        win_rate = (values > 0).mean() * 100

        print(
            f"Q{q} : "
            f"N={len(values):,} | "
            f"Future={avg_return:+.3f}% | "
            f"WR={win_rate:.1f}%"
        )

# -------------------------------------------------------------------
# 8. Analyse Up_Days_5
# -------------------------------------------------------------------

print("\n")
print("=" * 70)
print("ANALYSE : NOMBRE DE JOURS POSITIFS SUR 5 JOURS")
print("=" * 70)

for n in range(0, 6):

    subset = df[
        df["Up_Days_5"] == n
    ]

    print(f"\n{n}/5 jours positifs")

    if len(subset) < 100:
        print(f"  Échantillon trop faible : {len(subset)}")
        continue

    for horizon in [
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
    ]:

        values = subset[horizon].dropna()

        if len(values) == 0:
            continue

        avg_return = values.mean() * 100
        win_rate = (values > 0).mean() * 100

        print(
            f"  {horizon}: "
            f"Future={avg_return:+.3f}% | "
            f"WR={win_rate:.1f}%"
        )

# -------------------------------------------------------------------
# 9. Résumé
# -------------------------------------------------------------------

print("\n")
print("=" * 70)
print("RÉSUMÉ")
print("=" * 70)

print("""
Ce test est EXPLORATOIRE.

Nous cherchons à savoir si :

1. Une série de plusieurs journées positives
   est suivie d'une continuation.

2. Une série de hausse plus longue produit
   une meilleure espérance future.

3. Le rendement accumulé pendant la série
   contient une information supplémentaire.

4. Le nombre de journées positives sur 5 jours
   est utile pour caractériser le momentum.

Aucun seuil de trading n'est choisi ici.

Si un facteur semble intéressant, il sera ensuite
testé hors échantillon puis en walk-forward.
""")

print("=" * 70)
print("ANALYSE TERMINÉE")
print("=" * 70)