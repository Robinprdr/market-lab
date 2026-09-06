import pandas as pd
import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = "backtest_v4_score5_trades.csv"

MIN_TRAIN_TRADES = 20
MIN_TEST_TRADES = 5

# Fenêtres walk-forward :
# 3 années d'apprentissage -> année suivante en test
WINDOWS = [
    ("2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("2022-01-01", "2025-01-01", "2025-01-01", "2026-01-01"),
]


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(INPUT_FILE)

if "Entry_Date" not in df.columns:
    raise ValueError("La colonne Entry_Date est absente.")

df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])

# Sécurité : uniquement les trades Score 5
if "Score" in df.columns:
    df = df[df["Score"] >= 5].copy()

# Win / Loss
df["Win"] = df["PnL"] > 0

print("=" * 70)
print("V4.1 — WIN RATE & TRADE QUALITY LAB")
print("=" * 70)

print(f"Trades Score 5 analysés : {len(df)}")

if len(df) == 0:
    raise ValueError("Aucun trade Score 5 trouvé.")


# ============================================================
# METRIQUES
# ============================================================

def metrics(data):
    if len(data) == 0:
        return {
            "n": 0,
            "win_rate": np.nan,
            "avg_pnl_pct": np.nan,
            "profit_factor": np.nan,
            "total_pnl_pct": np.nan,
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
        "avg_pnl_pct": data["PnL_Pct"].mean() * 100,
        "profit_factor": pf,
        "total_pnl_pct": data["PnL_Pct"].sum() * 100,
    }


# ============================================================
# BASELINE
# ============================================================

base = metrics(df)

print("\nBASELINE SCORE 5")
print("-" * 70)
print(f"Trades           : {base['n']}")
print(f"Win rate         : {base['win_rate']:.2f}%")
print(f"Avg PnL/trade    : {base['avg_pnl_pct']:.3f}%")
print(f"Profit Factor    : {base['profit_factor']:.2f}")
print(f"PnL cumulée      : {base['total_pnl_pct']:.2f}%")


# ============================================================
# FACTEURS PRE-ENTREE
# ============================================================

FEATURES = [
    "Signal_Drop",
    "Distance_SMA20",
    "Distance_SMA50",
    "Distance_SMA200",
    "Return_3D",
    "Return_5D",
    "Return_10D",
    "ATR_Pct",
    "Drop_ATR_Ratio",
    "Volume_Ratio",
    "Negative_Days_5",
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio",
]


# Garder uniquement les colonnes disponibles
FEATURES = [f for f in FEATURES if f in df.columns]

print("\nFacteurs analysés :")
for feature in FEATURES:
    print(" -", feature)


# ============================================================
# WALK-FORWARD
# ============================================================

results = []

print("\n")
print("=" * 70)
print("WALK-FORWARD")
print("=" * 70)


for train_start, train_end, test_start, test_end in WINDOWS:

    train = df[
        (df["Entry_Date"] >= train_start)
        & (df["Entry_Date"] < train_end)
    ].copy()

    test = df[
        (df["Entry_Date"] >= test_start)
        & (df["Entry_Date"] < test_end)
    ].copy()

    print("\n")
    print(f"TRAIN : {train_start} -> {train_end}")
    print(f"TEST  : {test_start} -> {test_end}")
    print(f"Trades train : {len(train)}")
    print(f"Trades test  : {len(test)}")

    if len(train) < MIN_TRAIN_TRADES or len(test) < MIN_TEST_TRADES:
        print("Fenêtre ignorée : trop peu de trades.")
        continue

    train_base = metrics(train)
    test_base = metrics(test)

    print(
        f"Baseline TEST : "
        f"{test_base['win_rate']:.1f}% win | "
        f"{test_base['avg_pnl_pct']:.3f}% avg"
    )

    for feature in FEATURES:

        train_feature = train.dropna(subset=[feature]).copy()
        test_feature = test.dropna(subset=[feature]).copy()

        if len(train_feature) < MIN_TRAIN_TRADES:
            continue

        # ----------------------------------------------------
        # Quartiles calculés UNIQUEMENT sur le TRAIN
        # ----------------------------------------------------

        try:
            train_feature["Quartile"] = pd.qcut(
                train_feature[feature],
                q=4,
                labels=False,
                duplicates="drop"
            )
        except Exception:
            continue

        # ----------------------------------------------------
        # Chercher le meilleur quartile sur TRAIN
        #
        # Critère :
        # 1. expectancy positive
        # 2. meilleur win rate
        # 3. PF en second critère
        # ----------------------------------------------------

        candidates = []

        for q in sorted(train_feature["Quartile"].dropna().unique()):

            subset = train_feature[
                train_feature["Quartile"] == q
            ]

            if len(subset) < MIN_TRAIN_TRADES:
                continue

            m = metrics(subset)

            # On préfère une espérance positive
            if m["avg_pnl_pct"] > 0:
                candidates.append(
                    (
                        m["win_rate"],
                        m["profit_factor"],
                        m["avg_pnl_pct"],
                        int(q),
                        len(subset),
                    )
                )

        if not candidates:
            continue

        # Win rate en premier,
        # PF ensuite,
        # expectancy ensuite
        candidates.sort(
            key=lambda x: (x[0], x[1], x[2]),
            reverse=True
        )

        best = candidates[0]

        best_train_win = best[0]
        best_train_pf = best[1]
        best_train_avg = best[2]
        best_quartile = best[3]
        best_train_n = best[4]

        # ----------------------------------------------------
        # Transformer les bornes TRAIN
        # ----------------------------------------------------

        q_low = train_feature[feature].quantile(
            best_quartile / 4
        )

        q_high = train_feature[feature].quantile(
            (best_quartile + 1) / 4
        )

        # ----------------------------------------------------
        # Appliquer EXACTEMENT ces bornes au TEST
        # ----------------------------------------------------

        test_filtered = test_feature[
            (test_feature[feature] >= q_low)
            & (test_feature[feature] <= q_high)
        ].copy()

        if len(test_filtered) < MIN_TEST_TRADES:
            continue

        test_m = metrics(test_filtered)

        results.append({
            "Train_Start": train_start,
            "Train_End": train_end,
            "Test_Start": test_start,
            "Test_End": test_end,

            "Feature": feature,

            "Quartile": best_quartile + 1,

            "Train_N": best_train_n,
            "Train_WinRate": best_train_win,
            "Train_AvgPnL": best_train_avg,
            "Train_PF": best_train_pf,

            "Test_N": test_m["n"],
            "Test_WinRate": test_m["win_rate"],
            "Test_AvgPnL": test_m["avg_pnl_pct"],
            "Test_PF": test_m["profit_factor"],
            "Test_TotalPnL": test_m["total_pnl_pct"],

            "Baseline_Test_WinRate": test_base["win_rate"],
            "Baseline_Test_AvgPnL": test_base["avg_pnl_pct"],

            "WinRate_Delta": (
                test_m["win_rate"]
                - test_base["win_rate"]
            ),

            "AvgPnL_Delta": (
                test_m["avg_pnl_pct"]
                - test_base["avg_pnl_pct"]
            ),
        })


# ============================================================
# RESULTATS
# ============================================================

results_df = pd.DataFrame(results)

if len(results_df) == 0:
    print("\nAucun résultat exploitable.")
    raise SystemExit


results_df.to_csv(
    "v41_factor_walkforward.csv",
    index=False
)


# ============================================================
# RESUME PAR FACTEUR
# ============================================================

summary = []

for feature in results_df["Feature"].unique():

    sub = results_df[
        results_df["Feature"] == feature
    ].copy()

    positive_wr = (
        sub["WinRate_Delta"] > 0
    ).sum()

    positive_pnl = (
        sub["AvgPnL_Delta"] > 0
    ).sum()

    positive_pf = (
        sub["Test_PF"] > 1
    ).sum()

    summary.append({
        "Feature": feature,
        "Windows": len(sub),

        "Positive_WinRate_Windows": positive_wr,
        "WinRate_Stability": positive_wr / len(sub),

        "Positive_AvgPnL_Windows": positive_pnl,
        "AvgPnL_Stability": positive_pnl / len(sub),

        "PF_Greater_1_Windows": positive_pf,
        "PF_Stability": positive_pf / len(sub),

        "Avg_Test_WinRate": sub["Test_WinRate"].mean(),
        "Avg_Test_AvgPnL": sub["Test_AvgPnL"].mean(),
        "Avg_Test_PF": sub["Test_PF"].mean(),

        "Avg_WinRate_Delta": sub["WinRate_Delta"].mean(),
        "Avg_AvgPnL_Delta": sub["AvgPnL_Delta"].mean(),

        "Total_Test_Trades": sub["Test_N"].sum(),
    })


summary_df = pd.DataFrame(summary)

summary_df = summary_df.sort_values(
    [
        "WinRate_Stability",
        "Avg_WinRate_Delta",
        "Avg_AvgPnL_Delta"
    ],
    ascending=False
)

summary_df.to_csv(
    "v41_factor_summary.csv",
    index=False
)


# ============================================================
# AFFICHAGE
# ============================================================

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

print("\n")
print("=" * 70)
print("CLASSEMENT DES FACTEURS")
print("=" * 70)

print(
    summary_df[
        [
            "Feature",
            "Windows",
            "Positive_WinRate_Windows",
            "WinRate_Stability",
            "Avg_Test_WinRate",
            "Avg_WinRate_Delta",
            "Avg_Test_AvgPnL",
            "Avg_AvgPnL_Delta",
            "Avg_Test_PF",
            "Total_Test_Trades",
        ]
    ].to_string(index=False)
)


# ============================================================
# MEILLEURS RESULTATS INDIVIDUELS
# ============================================================

print("\n")
print("=" * 70)
print("MEILLEURES CONDITIONS OUT-OF-SAMPLE")
print("=" * 70)

best_results = results_df.sort_values(
    ["WinRate_Delta", "AvgPnL_Delta"],
    ascending=False
).head(15)

print(
    best_results[
        [
            "Feature",
            "Test_Start",
            "Test_End",
            "Quartile",
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


print("\n")
print("=" * 70)
print("FICHIERS CREES")
print("=" * 70)
print("v41_factor_walkforward.csv")
print("v41_factor_summary.csv")
print("=" * 70)