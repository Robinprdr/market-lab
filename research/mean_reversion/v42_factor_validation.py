import pandas as pd
import numpy as np


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = "results/mean_reversion/backtest_v4_score5_trades.csv"

# Facteurs retenus par V4.1
FACTORS = [
    "Return_5D",
    "Distance_SMA50",
    "ATR_Pct",
]

# On teste plusieurs seuils simples.
# Les seuils sont choisis dans le TRAIN uniquement.
MIN_TRAIN_TRADES = 25
MIN_TEST_TRADES = 8


WINDOWS = [
    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("2022-01-01", "2025-01-01", "2025-01-01", "2026-01-01"),
]


# ============================================================
# LOAD
# ============================================================

df = pd.read_csv(INPUT_FILE)

df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])

# Sécurité : uniquement Score 5
if "Score" in df.columns:
    df = df[df["Score"] >= 5].copy()

df["Win"] = df["PnL"] > 0


# ============================================================
# METRICS
# ============================================================

def metrics(data):

    if len(data) == 0:
        return {
            "n": 0,
            "win_rate": np.nan,
            "avg_pnl": np.nan,
            "profit_factor": np.nan,
            "total_pnl": 0,
        }

    wins = data.loc[data["PnL"] > 0, "PnL"]
    losses = data.loc[data["PnL"] < 0, "PnL"]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = np.inf

    return {
        "n": len(data),
        "win_rate": data["Win"].mean() * 100,
        "avg_pnl": data["PnL_Pct"].mean() * 100,
        "profit_factor": pf,
        "total_pnl": data["PnL_Pct"].sum() * 100,
    }


# ============================================================
# BASELINE
# ============================================================

baseline = metrics(df)

print("=" * 75)
print("V4.2 — FACTOR VALIDATION")
print("=" * 75)

print(f"Score 5 : {len(df)} trades")
print(f"Win rate : {baseline['win_rate']:.2f}%")
print(f"Avg PnL  : {baseline['avg_pnl']:.3f}%")
print(f"PF       : {baseline['profit_factor']:.2f}")
print(f"Total    : {baseline['total_pnl']:.2f}%")


# ============================================================
# TEST D'UNE CONDITION
# ============================================================

def evaluate_condition(train, test, factor, operator, threshold):

    # TRAIN
    if operator == ">=":
        train_selected = train[train[factor] >= threshold]
        test_selected = test[test[factor] >= threshold]

    elif operator == "<=":
        train_selected = train[train[factor] <= threshold]
        test_selected = test[test[factor] <= threshold]

    elif operator == ">":
        train_selected = train[train[factor] > threshold]
        test_selected = test[test[factor] > threshold]

    elif operator == "<":
        train_selected = train[train[factor] < threshold]
        test_selected = test[test[factor] < threshold]

    else:
        return None

    if len(train_selected) < MIN_TRAIN_TRADES:
        return None

    if len(test_selected) < MIN_TEST_TRADES:
        return None

    train_m = metrics(train_selected)
    test_m = metrics(test_selected)

    return train_m, test_m


# ============================================================
# WALK FORWARD
# ============================================================

all_results = []


for train_start, train_end, test_start, test_end in WINDOWS:

    train = df[
        (df["Entry_Date"] >= train_start)
        & (df["Entry_Date"] < train_end)
    ].copy()

    test = df[
        (df["Entry_Date"] >= test_start)
        & (df["Entry_Date"] < test_end)
    ].copy()

    if len(train) < MIN_TRAIN_TRADES:
        continue

    if len(test) < MIN_TEST_TRADES:
        continue

    train_base = metrics(train)
    test_base = metrics(test)

    print("\n" + "=" * 75)
    print(f"TRAIN {train_start} -> {train_end}")
    print(f"TEST  {test_start} -> {test_end}")
    print(f"Train : {len(train)} trades")
    print(f"Test  : {len(test)} trades")
    print(
        f"Baseline TEST : "
        f"{test_base['win_rate']:.1f}% win | "
        f"{test_base['avg_pnl']:.3f}% avg | "
        f"PF {test_base['profit_factor']:.2f}"
    )

    for factor in FACTORS:

        if factor not in train.columns:
            continue

        train_factor = train.dropna(subset=[factor]).copy()
        test_factor = test.dropna(subset=[factor]).copy()

        if len(train_factor) < MIN_TRAIN_TRADES:
            continue

        # ----------------------------------------------------
        # Seuils candidats calculés UNIQUEMENT sur TRAIN
        # ----------------------------------------------------

        quantiles = [
            0.20,
            0.30,
            0.40,
            0.50,
            0.60,
            0.70,
            0.80,
        ]

        thresholds = sorted(
            set(
                train_factor[factor]
                .quantile(quantiles)
                .round(6)
                .tolist()
            )
        )

        candidates = []

        # ----------------------------------------------------
        # Test des conditions
        # ----------------------------------------------------

        for threshold in thresholds:

            for operator in [">=", "<="]:

                result = evaluate_condition(
                    train_factor,
                    test_factor,
                    factor,
                    operator,
                    threshold
                )

                if result is None:
                    continue

                train_m, test_m = result

                # IMPORTANT :
                # On cherche une amélioration du win rate
                # MAIS uniquement si l'espérance TRAIN reste positive.
                if train_m["avg_pnl"] <= 0:
                    continue

                candidates.append({
                    "factor": factor,
                    "operator": operator,
                    "threshold": threshold,
                    "train": train_m,
                    "test": test_m,
                })

        if not candidates:
            continue

        # ----------------------------------------------------
        # Choix du meilleur seuil UNIQUEMENT sur TRAIN
        #
        # 1. Win rate
        # 2. Avg PnL
        # 3. Profit Factor
        # ----------------------------------------------------

        candidates.sort(
            key=lambda x: (
                x["train"]["win_rate"],
                x["train"]["avg_pnl"],
                x["train"]["profit_factor"],
            ),
            reverse=True
        )

        best = candidates[0]

        test_m = best["test"]

        result = {
            "Train_Start": train_start,
            "Train_End": train_end,
            "Test_Start": test_start,
            "Test_End": test_end,

            "Factor": factor,
            "Operator": best["operator"],
            "Threshold": best["threshold"],

            "Train_N": best["train"]["n"],
            "Train_WinRate": best["train"]["win_rate"],
            "Train_AvgPnL": best["train"]["avg_pnl"],
            "Train_PF": best["train"]["profit_factor"],

            "Test_N": test_m["n"],
            "Test_WinRate": test_m["win_rate"],
            "Test_AvgPnL": test_m["avg_pnl"],
            "Test_PF": test_m["profit_factor"],
            "Test_TotalPnL": test_m["total_pnl"],

            "Baseline_Test_WinRate": test_base["win_rate"],
            "Baseline_Test_AvgPnL": test_base["avg_pnl"],
            "Baseline_Test_PF": test_base["profit_factor"],

            "WinRate_Delta": (
                test_m["win_rate"]
                - test_base["win_rate"]
            ),

            "AvgPnL_Delta": (
                test_m["avg_pnl"]
                - test_base["avg_pnl"]
            ),

            "PF_Delta": (
                test_m["profit_factor"]
                - test_base["profit_factor"]
            ),
        }

        all_results.append(result)

        print(
            f"\n{factor}"
            f" -> {best['operator']} {best['threshold']:.4f}"
        )

        print(
            f"   TRAIN : "
            f"{best['train']['win_rate']:.1f}% win | "
            f"{best['train']['avg_pnl']:.3f}% avg | "
            f"PF {best['train']['profit_factor']:.2f}"
        )

        print(
            f"   TEST  : "
            f"{test_m['win_rate']:.1f}% win | "
            f"{test_m['avg_pnl']:.3f}% avg | "
            f"PF {test_m['profit_factor']:.2f}"
        )

        print(
            f"   DELTA : "
            f"{result['WinRate_Delta']:+.1f} pts win | "
            f"{result['AvgPnL_Delta']:+.3f}% avg"
        )


# ============================================================
# SAVE
# ============================================================

results_df = pd.DataFrame(all_results)

if len(results_df) == 0:
    print("\nAucun résultat.")
    raise SystemExit


results_df.to_csv(
    "results/mean_reversion/v42_factor_validation.csv",
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

summary = []

for factor in FACTORS:

    sub = results_df[
        results_df["Factor"] == factor
    ].copy()

    if len(sub) == 0:
        continue

    summary.append({
        "Factor": factor,

        "Windows": len(sub),

        "Positive_WinRate": (
            sub["WinRate_Delta"] > 0
        ).sum(),

        "WinRate_Stability": (
            sub["WinRate_Delta"] > 0
        ).mean() * 100,

        "Positive_AvgPnL": (
            sub["AvgPnL_Delta"] > 0
        ).sum(),

        "Avg_Test_WinRate": sub["Test_WinRate"].mean(),

        "Avg_WinRate_Delta": sub["WinRate_Delta"].mean(),

        "Avg_Test_PnL": sub["Test_AvgPnL"].mean(),

        "Avg_PnL_Delta": sub["AvgPnL_Delta"].mean(),

        "Avg_Test_PF": sub["Test_PF"].mean(),

        "Total_Test_Trades": sub["Test_N"].sum(),
    })


summary_df = pd.DataFrame(summary)

summary_df = summary_df.sort_values(
    [
        "Positive_WinRate",
        "Avg_WinRate_Delta",
        "Avg_PnL_Delta",
    ],
    ascending=False
)

summary_df.to_csv(
    "results/mean_reversion/v42_factor_summary.csv",
    index=False
)


# ============================================================
# FINAL OUTPUT
# ============================================================

print("\n")
print("=" * 75)
print("RESUME V4.2")
print("=" * 75)

print(
    summary_df.to_string(index=False)
)

print("\n")
print("=" * 75)
print("MEILLEURES CONDITIONS TEST")
print("=" * 75)

best = results_df.sort_values(
    [
        "WinRate_Delta",
        "AvgPnL_Delta",
    ],
    ascending=False
).head(15)

print(
    best[
        [
            "Factor",
            "Test_Start",
            "Operator",
            "Threshold",
            "Test_N",
            "Test_WinRate",
            "Baseline_Test_WinRate",
            "WinRate_Delta",
            "Test_AvgPnL",
            "AvgPnL_Delta",
            "Test_PF",
        ]
    ].to_string(index=False)
)

print("\nFichiers créés :")
print(" - results/mean_reversion/v42_factor_validation.csv")
print(" - results/mean_reversion/v42_factor_summary.csv")
print("=" * 75)