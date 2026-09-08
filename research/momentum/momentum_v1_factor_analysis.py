from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")
OUTPUT_DIR = Path("results/momentum")

OUTPUT_FACTOR = OUTPUT_DIR / "momentum_v1_factor_analysis.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "momentum_v1_factor_summary.csv"

N_QUANTILES = 5

FACTORS = [
    "Return_1D",
    "Return_3D",
    "Return_5D",
    "Return_10D",
    "Return_20D",
    "Distance_SMA20",
    "Distance_SMA50",
    "Distance_SMA200",
    "SMA20_vs_SMA50",
    "SMA50_vs_SMA200",
    "Volume_Ratio",
    "ATR_Pct",
    "Positive_Days_5",
    "Positive_Days_10",
    "Momentum_Acceleration_5D",
    "SPY_Return_1D",
    "SPY_Return_5D",
    "SPY_Return_10D",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio",
]

TARGETS = [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]


# ============================================================
# UTILITAIRES
# ============================================================

def pct(value):
    """Convertit une valeur décimale en pourcentage lisible."""
    return value * 100


def safe_mean(series):
    if len(series) == 0:
        return np.nan
    return series.mean()


def safe_median(series):
    if len(series) == 0:
        return np.nan
    return series.median()


def win_rate(series):
    if len(series) == 0:
        return np.nan
    return (series > 0).mean()


def assign_quantiles(series, n_quantiles=5):
    """
    Classe les observations en quantiles.
    Q1 = valeurs faibles
    Q5 = valeurs fortes

    duplicates='drop' évite les erreurs lorsque plusieurs
    valeurs sont identiques.
    """
    try:
        return pd.qcut(
            series,
            q=n_quantiles,
            labels=False,
            duplicates="drop",
        ) + 1
    except ValueError:
        return pd.Series(np.nan, index=series.index)


# ============================================================
# ANALYSE D'UN FACTEUR
# ============================================================

def analyze_factor(df, factor, target):
    """
    Analyse la relation entre un facteur et un rendement futur.

    IMPORTANT :
    Cette analyse est descriptive.
    Elle ne constitue PAS encore une stratégie de trading.
    """

    data = df[[factor, target]].dropna().copy()

    if len(data) < 50:
        return []

    data["Quantile"] = assign_quantiles(
        data[factor],
        N_QUANTILES,
    )

    data = data.dropna(subset=["Quantile"])

    results = []

    for quantile in sorted(data["Quantile"].unique()):

        subset = data[data["Quantile"] == quantile]

        if len(subset) == 0:
            continue

        future_return = subset[target]

        results.append(
            {
                "Factor": factor,
                "Target": target,
                "Quantile": int(quantile),
                "Trades": len(subset),
                "Average_Future_Return": future_return.mean(),
                "Median_Future_Return": future_return.median(),
                "Win_Rate": (future_return > 0).mean(),
                "Std_Future_Return": future_return.std(),
                "Min_Future_Return": future_return.min(),
                "Max_Future_Return": future_return.max(),
                "Average_Future_Return_Pct": pct(
                    future_return.mean()
                ),
                "Median_Future_Return_Pct": pct(
                    future_return.median()
                ),
                "Win_Rate_Pct": pct(
                    (future_return > 0).mean()
                ),
            }
        )

    return results


# ============================================================
# MONOTONICITÉ
# ============================================================

def calculate_monotonicity(factor_results):
    """
    Mesure simplement si les performances augmentent
    globalement de Q1 vers Q5.

    Exemple :

        Q1 : +0.05%
        Q2 : +0.10%
        Q3 : +0.15%
        Q4 : +0.22%
        Q5 : +0.30%

    => relation monotone positive.

    Ce n'est PAS un test statistique complet.
    C'est un indicateur exploratoire.
    """

    values = (
        factor_results
        .sort_values("Quantile")[
            "Average_Future_Return"
        ]
        .values
    )

    if len(values) < 3:
        return np.nan

    differences = np.diff(values)

    positive_moves = np.sum(differences > 0)
    negative_moves = np.sum(differences < 0)

    if positive_moves > negative_moves:
        return 1

    if negative_moves > positive_moves:
        return -1

    return 0


# ============================================================
# ANALYSE GLOBALE
# ============================================================

def main():

    print("=" * 70)
    print("MOMENTUM V1 - FACTOR ANALYSIS")
    print("=" * 70)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {INPUT_FILE}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # CHARGEMENT
    # --------------------------------------------------------

    df = pd.read_csv(INPUT_FILE)

    print()
    print(f"Fichier chargé : {INPUT_FILE}")
    print(f"Lignes : {len(df):,}")
    print(f"Actions : {df['Ticker'].nunique()}")

    # --------------------------------------------------------
    # VÉRIFICATION DES FACTEURS
    # --------------------------------------------------------

    available_factors = [
        factor
        for factor in FACTORS
        if factor in df.columns
    ]

    missing_factors = [
        factor
        for factor in FACTORS
        if factor not in df.columns
    ]

    print()
    print("Facteurs disponibles :")
    for factor in available_factors:
        print(f"  ✓ {factor}")

    if missing_factors:
        print()
        print("Facteurs manquants :")
        for factor in missing_factors:
            print(f"  ✗ {factor}")

    available_targets = [
        target
        for target in TARGETS
        if target in df.columns
    ]

    print()
    print("Horizons futurs disponibles :")
    for target in available_targets:
        print(f"  ✓ {target}")

    # --------------------------------------------------------
    # ANALYSE QUANTILES
    # --------------------------------------------------------

    all_results = []

    print()
    print("Analyse des facteurs...")
    print()

    for factor in available_factors:

        print(f"  {factor}")

        for target in available_targets:

            results = analyze_factor(
                df,
                factor,
                target,
            )

            all_results.extend(results)

    results_df = pd.DataFrame(all_results)

    # --------------------------------------------------------
    # SAUVEGARDE DÉTAILLÉE
    # --------------------------------------------------------

    results_df.to_csv(
        OUTPUT_FACTOR,
        index=False,
    )

    print()
    print(f"✓ Analyse détaillée : {OUTPUT_FACTOR}")

    # --------------------------------------------------------
    # RÉSUMÉ DES FACTEURS
    # --------------------------------------------------------

    summary_rows = []

    for factor in available_factors:

        for target in available_targets:

            subset = results_df[
                (results_df["Factor"] == factor)
                & (results_df["Target"] == target)
            ].copy()

            if subset.empty:
                continue

            subset = subset.sort_values("Quantile")

            q1 = subset.iloc[0]
            q5 = subset.iloc[-1]

            monotonicity = calculate_monotonicity(
                subset
            )

            spread = (
                q5["Average_Future_Return"]
                - q1["Average_Future_Return"]
            )

            summary_rows.append(
                {
                    "Factor": factor,
                    "Target": target,
                    "Q1_Avg_Return_Pct":
                        q1["Average_Future_Return_Pct"],
                    "Q5_Avg_Return_Pct":
                        q5["Average_Future_Return_Pct"],
                    "Q1_Win_Rate_Pct":
                        q1["Win_Rate_Pct"],
                    "Q5_Win_Rate_Pct":
                        q5["Win_Rate_Pct"],
                    "Q5_minus_Q1_Return_Pct":
                        pct(spread),
                    "Monotonicity":
                        monotonicity,
                    "Total_Observations":
                        subset["Trades"].sum(),
                }
            )

    summary_df = pd.DataFrame(summary_rows)

    summary_df.to_csv(
        OUTPUT_SUMMARY,
        index=False,
    )

    print(
        f"✓ Résumé : {OUTPUT_SUMMARY}"
    )

    # --------------------------------------------------------
    # AFFICHAGE DES FACTEURS LES PLUS INTÉRESSANTS
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("FACTEURS LES PLUS INTÉRESSANTS")
    print("=" * 70)

    for target in available_targets:

        target_summary = summary_df[
            summary_df["Target"] == target
        ].copy()

        target_summary = target_summary.sort_values(
            "Q5_minus_Q1_Return_Pct",
            ascending=False,
        )

        print()
        print(f"--- {target} ---")

        for _, row in target_summary.head(10).iterrows():

            direction = "↑"

            if row["Q5_minus_Q1_Return_Pct"] < 0:
                direction = "↓"

            print(
                f"{direction} "
                f"{row['Factor']:<28} "
                f"Q1={row['Q1_Avg_Return_Pct']:+.3f}% "
                f"Q5={row['Q5_Avg_Return_Pct']:+.3f}% "
                f"spread={row['Q5_minus_Q1_Return_Pct']:+.3f}% "
                f"WR Q5={row['Q5_Win_Rate_Pct']:.1f}%"
            )

    # --------------------------------------------------------
    # INTERPRÉTATION AUTOMATIQUE PRUDENTE
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("INTERPRÉTATION")
    print("=" * 70)

    print(
        """
Cette analyse est EXPLORATOIRE.

Elle sert à identifier les facteurs qui semblent
associés à une continuation du mouvement.

Un facteur intéressant doit idéalement montrer :

1. Une différence claire entre Q1 et Q5.
2. Une relation relativement monotone entre les quantiles.
3. Une amélioration du taux de réussite.
4. Une certaine cohérence entre plusieurs horizons.
5. Une taille d'échantillon suffisante.

ATTENTION :
Nous ne choisissons PAS encore les seuils de la stratégie.

Les meilleurs facteurs observés ici seront ensuite
testés hors échantillon et en walk-forward.

Le but est d'éviter de créer une stratégie qui
fonctionne uniquement parce qu'elle a été optimisée
sur l'historique que nous avons déjà regardé.
"""
    )

    print()
    print("Momentum V1 Factor Analysis terminée.")
    print("=" * 70)


if __name__ == "__main__":
    main()