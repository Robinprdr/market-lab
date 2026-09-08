import pandas as pd
import numpy as np
from pathlib import Path

# ================================================================
# MOMENTUM V1 - OUT OF SAMPLE TEST
# ================================================================

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")

TRAIN_END = "2023-01-01"

OUTPUT_FILE = Path(
    "results/momentum/momentum_v1_oos_results.csv"
)

FACTORS = [
    "ATR_Pct",
    "Return_10D",
]

HORIZONS = [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]

print("=" * 70)
print("MOMENTUM V1 - OUT OF SAMPLE TEST")
print("=" * 70)

# ================================================================
# 1. CHARGEMENT
# ================================================================

df = pd.read_csv(INPUT_FILE)

df["Date"] = pd.to_datetime(df["Date"])

df = df.sort_values(
    ["Ticker", "Date"]
).reset_index(drop=True)

print(f"\nFichier chargé : {INPUT_FILE}")
print(f"Lignes : {len(df):,}")
print(f"Actions : {df['Ticker'].nunique()}")

# ================================================================
# 2. TRAIN / TEST
# ================================================================

train = df[df["Date"] < TRAIN_END].copy()
test = df[df["Date"] >= TRAIN_END].copy()

print("\n" + "=" * 70)
print("SÉPARATION TRAIN / TEST")
print("=" * 70)

print(
    f"\nTRAIN : "
    f"{train['Date'].min().date()} → "
    f"{train['Date'].max().date()}"
)

print(
    f"TEST  : "
    f"{test['Date'].min().date()} → "
    f"{test['Date'].max().date()}"
)

print(f"\nLignes TRAIN : {len(train):,}")
print(f"Lignes TEST  : {len(test):,}")

# ================================================================
# 3. FONCTION D'ANALYSE
# ================================================================

results = []


def analyse_subset(
    subset,
    label,
    factor,
    horizon
):
    values = subset[horizon].dropna()

    if len(values) == 0:
        return

    avg_return = values.mean() * 100
    median_return = values.median() * 100
    win_rate = (values > 0).mean() * 100

    results.append({
        "Dataset": label,
        "Factor": factor,
        "Horizon": horizon,
        "N": len(values),
        "Average_Return": avg_return,
        "Median_Return": median_return,
        "Win_Rate": win_rate,
    })


# ================================================================
# 4. BASELINE TEST
# ================================================================

print("\n" + "=" * 70)
print("BASELINE - TEST")
print("=" * 70)

for horizon in HORIZONS:

    values = test[horizon].dropna()

    print(
        f"\n{horizon}"
    )

    print(
        f"  N={len(values):,} | "
        f"Future={values.mean() * 100:+.3f}% | "
        f"WR={(values > 0).mean() * 100:.1f}%"
    )

    analyse_subset(
        test,
        "TEST_BASELINE",
        "None",
        horizon
    )


# ================================================================
# 5. CALCUL DES SEUILS UNIQUEMENT SUR LE TRAIN
# ================================================================

print("\n" + "=" * 70)
print("SEUILS CALCULÉS UNIQUEMENT SUR LE TRAIN")
print("=" * 70)

thresholds = {}

for factor in FACTORS:

    values = train[factor].dropna()

    q20 = values.quantile(0.20)
    q40 = values.quantile(0.40)
    q60 = values.quantile(0.60)
    q80 = values.quantile(0.80)

    thresholds[factor] = {
        "Q20": q20,
        "Q40": q40,
        "Q60": q60,
        "Q80": q80,
    }

    print(f"\n{factor}")

    print(f"  Q20 = {q20:.6f}")
    print(f"  Q40 = {q40:.6f}")
    print(f"  Q60 = {q60:.6f}")
    print(f"  Q80 = {q80:.6f}")


# ================================================================
# 6. TEST OOS FACTEUR PAR FACTEUR
# ================================================================

print("\n" + "=" * 70)
print("TEST OOS DES FACTEURS")
print("=" * 70)

for factor in FACTORS:

    q80 = thresholds[factor]["Q80"]

    print("\n" + "-" * 70)
    print(f"FACTEUR : {factor}")
    print(f"Condition OOS : {factor} >= seuil Q80 du TRAIN")
    print(f"Seuil : {q80:.6f}")
    print("-" * 70)

    subset = test[
        test[factor] >= q80
    ].copy()

    print(
        f"\nObservations sélectionnées : "
        f"{len(subset):,} "
        f"({len(subset) / len(test) * 100:.1f}% du TEST)"
    )

    for horizon in HORIZONS:

        values = subset[horizon].dropna()

        if len(values) == 0:
            continue

        avg_return = values.mean() * 100
        median_return = values.median() * 100
        win_rate = (values > 0).mean() * 100

        print(
            f"\n{horizon}"
        )

        print(
            f"  N={len(values):,} | "
            f"Mean={avg_return:+.3f}% | "
            f"Median={median_return:+.3f}% | "
            f"WR={win_rate:.1f}%"
        )

        analyse_subset(
            subset,
            "TEST_Q80",
            factor,
            horizon
        )


# ================================================================
# 7. COMBINAISON ATR + RETURN 10D
# ================================================================

print("\n" + "=" * 70)
print("COMBINAISON ATR_Pct + Return_10D")
print("=" * 70)

atr_threshold = thresholds["ATR_Pct"]["Q80"]
ret_threshold = thresholds["Return_10D"]["Q80"]

combined = test[
    (test["ATR_Pct"] >= atr_threshold)
    &
    (test["Return_10D"] >= ret_threshold)
].copy()

print(
    f"\nCondition : "
    f"ATR_Pct >= {atr_threshold:.6f}"
)

print(
    f"AND Return_10D >= {ret_threshold:.6f}"
)

print(
    f"\nObservations sélectionnées : "
    f"{len(combined):,} "
    f"({len(combined) / len(test) * 100:.1f}% du TEST)"
)

for horizon in HORIZONS:

    values = combined[horizon].dropna()

    if len(values) == 0:
        continue

    avg_return = values.mean() * 100
    median_return = values.median() * 100
    win_rate = (values > 0).mean() * 100

    print(
        f"\n{horizon}"
    )

    print(
        f"  N={len(values):,} | "
        f"Mean={avg_return:+.3f}% | "
        f"Median={median_return:+.3f}% | "
        f"WR={win_rate:.1f}%"
    )

    analyse_subset(
        combined,
        "TEST_COMBINED_Q80",
        "ATR_Pct + Return_10D",
        horizon
    )


# ================================================================
# 8. COMPARAISON AVEC LE BASELINE
# ================================================================

print("\n" + "=" * 70)
print("COMPARAISON OOS")
print("=" * 70)

summary = pd.DataFrame(results)

if len(summary) > 0:

    baseline = summary[
        summary["Dataset"] == "TEST_BASELINE"
    ][
        ["Horizon", "Average_Return"]
    ].rename(
        columns={
            "Average_Return": "Baseline_Return"
        }
    )

    factors = summary[
        summary["Dataset"] != "TEST_BASELINE"
    ].merge(
        baseline,
        on="Horizon",
        how="left"
    )

    factors["Excess_vs_Baseline"] = (
        factors["Average_Return"]
        -
        factors["Baseline_Return"]
    )

    print()

    for _, row in factors.iterrows():

        print(
            f"{row['Factor']:25s} | "
            f"{row['Horizon']:18s} | "
            f"Mean={row['Average_Return']:+.3f}% | "
            f"Baseline={row['Baseline_Return']:+.3f}% | "
            f"Diff={row['Excess_vs_Baseline']:+.3f}% | "
            f"WR={row['Win_Rate']:.1f}%"
        )

# ================================================================
# 9. SAUVEGARDE
# ================================================================

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

summary.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\n" + "=" * 70)
print("RÉSUMÉ")
print("=" * 70)

print(
    """
Ce test est véritablement OUT OF SAMPLE.

Les seuils Q80 ont été calculés uniquement
sur la période TRAIN.

Ils sont ensuite appliqués tels quels
sur la période TEST.

Aucun seuil n'a été optimisé sur le TEST.

Nous cherchons principalement à vérifier :

1. ATR_Pct conserve-t-il son intérêt ?
2. Return_10D conserve-t-il son intérêt ?
3. La combinaison ATR_Pct + Return_10D
   apporte-t-elle quelque chose ?
4. Le résultat est-il supérieur au baseline ?
5. Le signal reste-t-il intéressant sur 1D / 3D / 5D ?

Ce n'est PAS encore un backtest de stratégie.

Nous testons uniquement la capacité prédictive
des facteurs.
"""
)

print(f"\n✓ Résultats sauvegardés : {OUTPUT_FILE}")

print("\n" + "=" * 70)
print("OOS TERMINÉ")
print("=" * 70)