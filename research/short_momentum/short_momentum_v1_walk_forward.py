import pandas as pd
import numpy as np

INPUT = "results/short_momentum/short_momentum_v1_research.csv"

df = pd.read_csv(INPUT)
df["Date"] = pd.to_datetime(df["Date"])

# ============================================================
# CONFIGURATION
# ============================================================

FACTOR_ATR = "ATR_Pct"
FACTOR_RET = "Return_3D"

HORIZONS = [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]

# Chaque fenêtre :
# TRAIN = toutes les années précédentes
# TEST  = l'année suivante

WINDOWS = [
    ("W1", "2018-10-16", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("W2", "2018-10-16", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("W3", "2018-10-16", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("W4", "2018-10-16", "2024-12-31", "2025-01-01", "2025-12-05"),
]

# ============================================================
# ANALYSE
# ============================================================

def analyze(data, horizon):

    values = data[horizon].dropna()

    if len(values) == 0:
        return None

    mean = values.mean()
    median = values.median()
    win_rate = (values < 0).mean()

    return {
        "mean": mean,
        "median": median,
        "win_rate": win_rate,
        "n": len(values),
    }


all_results = []

print("=" * 90)
print("SHORT MOMENTUM V1 — WALK-FORWARD")
print("=" * 90)
print()

print("SIGNAL : ATR_Pct élevé + Return_3D très négatif")
print("SHORT  : rendement futur négatif = GAIN")
print()

# ============================================================
# WALK-FORWARD
# ============================================================

for name, train_start, train_end, test_start, test_end in WINDOWS:

    train = df[
        (df["Date"] >= train_start) &
        (df["Date"] <= train_end)
    ].copy()

    test = df[
        (df["Date"] >= test_start) &
        (df["Date"] <= test_end)
    ].copy()

    # --------------------------------------------------------
    # SEUILS CALCULÉS UNIQUEMENT SUR LE TRAIN
    # --------------------------------------------------------

    atr_threshold = train[FACTOR_ATR].quantile(0.80)
    ret_threshold = train[FACTOR_RET].quantile(0.20)

    # --------------------------------------------------------
    # SIGNAL TEST
    # --------------------------------------------------------

    signal = test[
        (test[FACTOR_ATR] >= atr_threshold) &
        (test[FACTOR_RET] <= ret_threshold)
    ].copy()

    print("=" * 90)
    print(f"{name} — TEST {test_start[:4]}")
    print("=" * 90)

    print(
        f"TRAIN : {train_start} -> {train_end} | "
        f"{len(train):,} observations"
    )

    print(
        f"TEST  : {test_start} -> {test_end} | "
        f"{len(test):,} observations"
    )

    print()

    print(f"ATR Q80    : {atr_threshold:.4%}")
    print(f"Return3D Q20 : {ret_threshold:.4%}")

    print()

    print(
        f"Signaux : {len(signal):,} "
        f"({len(signal) / len(test) * 100:.2f}% du test)"
    )

    print()

    for horizon in HORIZONS:

        baseline_stats = analyze(test, horizon)
        signal_stats = analyze(signal, horizon)

        if signal_stats is None:
            continue

        excess = (
            signal_stats["mean"] -
            baseline_stats["mean"]
        )

        print(
            f"{horizon:<22} "
            f"Signal {signal_stats['mean']:+.3%} | "
            f"Baseline {baseline_stats['mean']:+.3%} | "
            f"Excess {excess:+.3%} | "
            f"WR {signal_stats['win_rate']:.1%} | "
            f"n={signal_stats['n']:,}"
        )

        all_results.append({
            "Window": name,
            "Test_Year": test_start[:4],
            "ATR_Threshold": atr_threshold,
            "Return3D_Threshold": ret_threshold,
            "Horizon": horizon,
            "Signal_Mean": signal_stats["mean"],
            "Baseline_Mean": baseline_stats["mean"],
            "Excess": excess,
            "Win_Rate": signal_stats["win_rate"],
            "Trades": signal_stats["n"],
        })

    print()

# ============================================================
# SYNTHÈSE
# ============================================================

results = pd.DataFrame(all_results)

print("=" * 90)
print("SYNTHÈSE WALK-FORWARD")
print("=" * 90)
print()

for horizon in HORIZONS:

    subset = results[
        results["Horizon"] == horizon
    ].copy()

    if len(subset) == 0:
        continue

    positive_windows = (
        subset["Signal_Mean"] < 0
    ).sum()

    mean_signal = subset["Signal_Mean"].mean()
    mean_excess = subset["Excess"].mean()
    total_trades = subset["Trades"].sum()
    mean_wr = subset["Win_Rate"].mean()

    print(
        f"{horizon:<22} "
        f"Signal moyen {mean_signal:+.3%} | "
        f"Excess moyen {mean_excess:+.3%} | "
        f"WR moyen {mean_wr:.1%} | "
        f"années positives {positive_windows}/{len(subset)} | "
        f"trades {total_trades:,}"
    )

print()

# ============================================================
# SCORE DE ROBUSTESSE
# ============================================================

print("=" * 90)
print("ÉVALUATION")
print("=" * 90)
print()

for horizon in HORIZONS:

    subset = results[
        results["Horizon"] == horizon
    ]

    if len(subset) == 0:
        continue

    positive_windows = (
        subset["Signal_Mean"] < 0
    ).sum()

    avg_excess = subset["Excess"].mean()

    if positive_windows == len(subset) and avg_excess < 0:
        verdict = "🟢 ROBUSTE"
    elif positive_windows >= 3 and avg_excess < 0:
        verdict = "🟢 PROMETTEUR"
    elif positive_windows >= 2 and avg_excess < 0:
        verdict = "🟡 MITIGÉ"
    else:
        verdict = "🔴 FAIBLE"

    print(
        f"{horizon:<22} {verdict}"
    )

print()

# ============================================================
# SAUVEGARDE
# ============================================================

OUTPUT = "results/short_momentum/short_momentum_v1_walk_forward.csv"

results.to_csv(OUTPUT, index=False)

print("=" * 90)
print("FIN")
print("=" * 90)
print()
print(f"Résultats sauvegardés : {OUTPUT}")
