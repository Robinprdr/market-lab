import pandas as pd
import numpy as np

INPUT = "results/short_momentum/short_momentum_v1_research.csv"

df = pd.read_csv(INPUT)
df["Date"] = pd.to_datetime(df["Date"])

# ============================================================
# CONFIGURATION OOS
# ============================================================

TRAIN_START = "2018-10-16"
TRAIN_END   = "2022-12-30"

TEST_START  = "2023-01-03"
TEST_END    = "2025-12-05"

# Facteurs de notre candidat
FACTOR_ATR = "ATR_Pct"
FACTOR_RET = "Return_3D"

HORIZONS = [
    "Future_Return_1D",
    "Future_Return_3D",
    "Future_Return_5D",
    "Future_Return_10D",
]

# ============================================================
# TRAIN / TEST
# ============================================================

train = df[
    (df["Date"] >= TRAIN_START) &
    (df["Date"] <= TRAIN_END)
].copy()

test = df[
    (df["Date"] >= TEST_START) &
    (df["Date"] <= TEST_END)
].copy()

print("=" * 80)
print("SHORT MOMENTUM V1 — OUT OF SAMPLE TEST")
print("=" * 80)
print()

print(f"TRAIN : {TRAIN_START} -> {TRAIN_END}")
print(f"TEST  : {TEST_START} -> {TEST_END}")
print()

print(f"Train observations : {len(train):,}")
print(f"Test observations  : {len(test):,}")
print()

# ============================================================
# SEUILS CALCULÉS UNIQUEMENT SUR LE TRAIN
# ============================================================

atr_threshold = train[FACTOR_ATR].quantile(0.80)
ret_threshold = train[FACTOR_RET].quantile(0.20)

print("=" * 80)
print("SEUILS CALCULÉS SUR LE TRAIN UNIQUEMENT")
print("=" * 80)
print()

print(f"ATR_Pct Q80     : {atr_threshold:.4%}")
print(f"Return_3D Q20   : {ret_threshold:.4%}")
print()

# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyze(label, data, horizon):

    values = data[horizon].dropna()

    if len(values) == 0:
        return

    mean = values.mean()
    median = values.median()

    # Pour un SHORT :
    # rendement futur négatif = gain
    win_rate = (values < 0).mean()

    print(
        f"{label:<38} "
        f"mean {mean:+.3%} | "
        f"median {median:+.3%} | "
        f"WR {win_rate:.1%} | "
        f"n={len(values):,}"
    )


# ============================================================
# SIGNALS TRAIN
# ============================================================

train_signal = train[
    (train[FACTOR_ATR] >= atr_threshold) &
    (train[FACTOR_RET] <= ret_threshold)
].copy()

# ============================================================
# SIGNALS TEST
# ============================================================

test_signal = test[
    (test[FACTOR_ATR] >= atr_threshold) &
    (test[FACTOR_RET] <= ret_threshold)
].copy()

# ============================================================
# BASELINES
# ============================================================

print("=" * 80)
print("BASELINE — TOUS LES SIGNAUX")
print("=" * 80)
print()

for horizon in HORIZONS:
    analyze("Baseline", test, horizon)

print()

# ============================================================
# TRAIN PERFORMANCE
# ============================================================

print("=" * 80)
print("TRAIN — PERFORMANCE DU SIGNAL")
print("=" * 80)
print()

for horizon in HORIZONS:
    analyze("ATR Q80 + Return_3D Q20", train_signal, horizon)

print()

# ============================================================
# OOS PERFORMANCE
# ============================================================

print("=" * 80)
print("TEST OOS — PERFORMANCE DU SIGNAL")
print("=" * 80)
print()

for horizon in HORIZONS:
    analyze("ATR Q80 + Return_3D Q20", test_signal, horizon)

print()

# ============================================================
# EXCESS RETURN VS BASELINE
# ============================================================

print("=" * 80)
print("OOS — EXCESS PAR RAPPORT AU BASELINE")
print("=" * 80)
print()

for horizon in HORIZONS:

    baseline = test[horizon].dropna()
    signal = test_signal[horizon].dropna()

    if len(baseline) == 0 or len(signal) == 0:
        continue

    baseline_mean = baseline.mean()
    signal_mean = signal.mean()

    excess = signal_mean - baseline_mean

    if signal_mean < 0 and excess < 0:
        verdict = "🟢 TRÈS BON"
    elif signal_mean < 0:
        verdict = "🟢 BON"
    elif signal_mean < baseline_mean:
        verdict = "🟡 MIEUX QUE BASELINE"
    else:
        verdict = "🔴 MAUVAIS"

    print(
        f"{horizon:<22} "
        f"Signal {signal_mean:+.3%} | "
        f"Baseline {baseline_mean:+.3%} | "
        f"Excess {excess:+.3%} | "
        f"{verdict}"
    )

print()

# ============================================================
# DISTRIBUTION DES SIGNAUX
# ============================================================

print("=" * 80)
print("DENSITÉ DU SIGNAL")
print("=" * 80)
print()

train_pct = len(train_signal) / len(train) * 100
test_pct = len(test_signal) / len(test) * 100

print(f"Train : {len(train_signal):,} signaux ({train_pct:.2f}%)")
print(f"Test  : {len(test_signal):,} signaux ({test_pct:.2f}%)")

print()

# ============================================================
# RÉSULTAT PAR ANNÉE
# ============================================================

print("=" * 80)
print("OOS PAR ANNÉE")
print("=" * 80)
print()

test_signal["Year"] = test_signal["Date"].dt.year

for year, group in test_signal.groupby("Year"):

    print(f"\n--- {year} ---")

    for horizon in HORIZONS:
        analyze(horizon, group, horizon)

print()

# ============================================================
# SAUVEGARDE
# ============================================================

output = "results/short_momentum/short_momentum_v1_oos_signals.csv"

test_signal.to_csv(output, index=False)

print("=" * 80)
print("FIN DE L'OOS")
print("=" * 80)
print()
print(f"Signaux OOS sauvegardés dans : {output}")
print()
print("RAPPEL SHORT :")
print("  rendement futur négatif = 🟢 BON")
print("  rendement futur positif = 🔴 MAUVAIS")
print()
