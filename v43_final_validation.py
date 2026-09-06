import pandas as pd
import numpy as np

FILE = "backtest_v4_score5_trades.csv"

# ============================================================
# PARAMÈTRES
# ============================================================

MIN_TRADES = 10

WINDOWS = [
    ("W1", "2018-01-01", "2021-01-01", "2021-01-01", "2022-01-01"),
    ("W2", "2019-01-01", "2022-01-01", "2022-01-01", "2023-01-01"),
    ("W3", "2020-01-01", "2023-01-01", "2023-01-01", "2024-01-01"),
    ("W4", "2021-01-01", "2024-01-01", "2024-01-01", "2025-01-01"),
    ("W5", "2022-01-01", "2025-01-01", "2025-01-01", "2026-01-01"),
]

# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])

# On travaille UNIQUEMENT avec les trades Score 5.
# Ce sont les setups les plus stricts de notre V1.
df = df[df["Score"] == 5].copy()

# On élimine les lignes inexploitables
required = [
    "Entry_Date",
    "PnL_Pct",
    "Distance_SMA50",
    "ATR_Pct",
]

missing = [c for c in required if c not in df.columns]

if missing:
    print("ERREUR : colonnes manquantes :", missing)
    print("Colonnes disponibles :")
    print(df.columns.tolist())
    raise SystemExit

df = df.dropna(subset=required).copy()

# ============================================================
# BASELINE
# ============================================================

def stats(data):
    if len(data) == 0:
        return {
            "trades": 0,
            "win_rate": np.nan,
            "avg_pnl": np.nan,
            "pf": np.nan,
            "total_pnl": np.nan,
        }

    wins = data[data["PnL_Pct"] > 0]["PnL_Pct"]
    losses = data[data["PnL_Pct"] < 0]["PnL_Pct"]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    return {
        "trades": len(data),
        "win_rate": (data["PnL_Pct"] > 0).mean() * 100,
        "avg_pnl": data["PnL_Pct"].mean() * 100,
        "pf": pf,
        "total_pnl": data["PnL_Pct"].sum() * 100,
    }


base = stats(df)

print("=" * 75)
print("V4.3 — FINAL VALIDATION MEAN REVERSION")
print("=" * 75)

print(f"\nScore 5 : {len(df)} trades")
print(
    f"Baseline : "
    f"WR {base['win_rate']:.2f}% | "
    f"Avg PnL {base['avg_pnl']:.3f}% | "
    f"PF {base['pf']:.2f} | "
    f"Total {base['total_pnl']:.2f}%"
)

# ============================================================
# CANDIDATS
# ============================================================

candidates = {
    "BASE": lambda x: pd.Series(True, index=x.index),

    # Distance SMA50
    "SMA50 >= 5%": lambda x: x["Distance_SMA50"] >= 0.05,
    "SMA50 >= 7.5%": lambda x: x["Distance_SMA50"] >= 0.075,
    "SMA50 >= 10%": lambda x: x["Distance_SMA50"] >= 0.10,

    # ATR
    "ATR <= 1.5%": lambda x: x["ATR_Pct"] <= 0.015,
    "ATR <= 2.0%": lambda x: x["ATR_Pct"] <= 0.020,
    "ATR <= 2.5%": lambda x: x["ATR_Pct"] <= 0.025,
    "ATR <= 3.0%": lambda x: x["ATR_Pct"] <= 0.030,

    # Combinaisons
    "SMA50 >= 5% + ATR <= 2.5%":
        lambda x: (
            (x["Distance_SMA50"] >= 0.05) &
            (x["ATR_Pct"] <= 0.025)
        ),

    "SMA50 >= 5% + ATR <= 3%":
        lambda x: (
            (x["Distance_SMA50"] >= 0.05) &
            (x["ATR_Pct"] <= 0.030)
        ),

    "SMA50 >= 7.5% + ATR <= 2.5%":
        lambda x: (
            (x["Distance_SMA50"] >= 0.075) &
            (x["ATR_Pct"] <= 0.025)
        ),

    "SMA50 >= 7.5% + ATR <= 3%":
        lambda x: (
            (x["Distance_SMA50"] >= 0.075) &
            (x["ATR_Pct"] <= 0.030)
        ),

    "SMA50 >= 10% + ATR <= 2.5%":
        lambda x: (
            (x["Distance_SMA50"] >= 0.10) &
            (x["ATR_Pct"] <= 0.025)
        ),
}

# ============================================================
# TEST GLOBAL
# ============================================================

print("\n" + "=" * 75)
print("TEST GLOBAL DES ZONES")
print("=" * 75)

global_results = []

for name, condition in candidates.items():

    subset = df[condition(df)].copy()

    if len(subset) < MIN_TRADES:
        continue

    s = stats(subset)

    global_results.append({
        "Candidate": name,
        "Trades": s["trades"],
        "WinRate": s["win_rate"],
        "AvgPnL": s["avg_pnl"],
        "PF": s["pf"],
        "TotalPnL": s["total_pnl"],
    })

results = pd.DataFrame(global_results)

results = results.sort_values(
    ["PF", "AvgPnL"],
    ascending=False
)

pd.set_option("display.max_rows", 100)
pd.set_option("display.width", 180)

print(
    results.to_string(
        index=False,
        formatters={
            "WinRate": "{:.2f}%".format,
            "AvgPnL": "{:.3f}%".format,
            "PF": "{:.2f}".format,
            "TotalPnL": "{:.2f}%".format,
        }
    )
)

# ============================================================
# WALK FORWARD
# ============================================================

print("\n" + "=" * 75)
print("WALK-FORWARD — VALIDATION HORS ÉCHANTILLON")
print("=" * 75)

wf_rows = []

for candidate_name, condition in candidates.items():

    if candidate_name == "BASE":
        continue

    test_stats = []

    print(f"\n--- {candidate_name} ---")

    for window_name, train_start, train_end, test_start, test_end in WINDOWS:

        train = df[
            (df["Entry_Date"] >= train_start) &
            (df["Entry_Date"] < train_end)
        ]

        test = df[
            (df["Entry_Date"] >= test_start) &
            (df["Entry_Date"] < test_end)
        ]

        train_filtered = train[condition(train)].copy()
        test_filtered = test[condition(test)].copy()

        if len(train_filtered) < MIN_TRADES:
            continue

        if len(test_filtered) < MIN_TRADES:
            continue

        tr = stats(train_filtered)
        te = stats(test_filtered)

        base_test = stats(test)

        wr_delta = te["win_rate"] - base_test["win_rate"]
        pnl_delta = te["avg_pnl"] - base_test["avg_pnl"]

        test_stats.append({
            "window": window_name,
            "trades": te["trades"],
            "win_rate": te["win_rate"],
            "avg_pnl": te["avg_pnl"],
            "pf": te["pf"],
            "wr_delta": wr_delta,
            "pnl_delta": pnl_delta,
            "total_pnl": te["total_pnl"],
        })

        print(
            f"{window_name} | "
            f"{te['trades']:3d} trades | "
            f"WR {te['win_rate']:5.1f}% | "
            f"ΔWR {wr_delta:+5.1f}pp | "
            f"Avg {te['avg_pnl']:+.3f}% | "
            f"ΔPnL {pnl_delta:+.3f}pp | "
            f"PF {te['pf']:.2f}"
        )

    if not test_stats:
        continue

    t = pd.DataFrame(test_stats)

    positive_wr = (t["wr_delta"] > 0).sum()
    positive_pnl = (t["pnl_delta"] > 0).sum()

    wf_rows.append({
        "Candidate": candidate_name,
        "Windows": len(t),
        "Positive_WR": positive_wr,
        "Positive_PnL": positive_pnl,
        "Avg_WR_Delta": t["wr_delta"].mean(),
        "Avg_PnL_Delta": t["pnl_delta"].mean(),
        "Avg_Test_WR": t["win_rate"].mean(),
        "Avg_Test_PnL": t["avg_pnl"].mean(),
        "Avg_PF": t["pf"].mean(),
        "Test_Trades": t["trades"].sum(),
        "Total_PnL": t["total_pnl"].sum(),
    })

# ============================================================
# RÉSUMÉ FINAL
# ============================================================

summary = pd.DataFrame(wf_rows)

print("\n" + "=" * 75)
print("RÉSUMÉ WALK-FORWARD")
print("=" * 75)

if len(summary) > 0:

    summary = summary.sort_values(
        ["Positive_WR", "Positive_PnL", "Avg_PnL_Delta"],
        ascending=False
    )

    print(
        summary.to_string(
            index=False,
            formatters={
                "Avg_WR_Delta": "{:+.2f}pp".format,
                "Avg_PnL_Delta": "{:+.3f}%".format,
                "Avg_Test_WR": "{:.2f}%".format,
                "Avg_Test_PnL": "{:+.3f}%".format,
                "Avg_PF": "{:.2f}".format,
                "Total_PnL": "{:+.2f}%".format,
            }
        )
    )

    # ========================================================
    # FILTRE DE ROBUSTESSE
    # ========================================================

    robust = summary[
        (summary["Windows"] >= 3) &
        (summary["Positive_WR"] >= 3) &
        (summary["Positive_PnL"] >= 3) &
        (summary["Avg_PnL_Delta"] >= 0) &
        (summary["Avg_PF"] > 1.10)
    ].copy()

    print("\n" + "=" * 75)
    print("CANDIDATS QUI PASSENT LE FILTRE DE ROBUSTESSE")
    print("=" * 75)

    if len(robust) == 0:
        print("\nAUCUN candidat ne passe tous les critères.")
        print("=> On ne force PAS une amélioration.")
        print("=> La Mean Reversion devra être retravaillée.")
    else:
        print(
            robust.to_string(
                index=False,
                formatters={
                    "Avg_WR_Delta": "{:+.2f}pp".format,
                    "Avg_PnL_Delta": "{:+.3f}%".format,
                    "Avg_Test_WR": "{:.2f}%".format,
                    "Avg_Test_PnL": "{:+.3f}%".format,
                    "Avg_PF": "{:.2f}".format,
                    "Total_PnL": "{:+.2f}%".format,
                }
            )
        )

        print("\n=> Ces candidats méritent un test dans le moteur OHLC.")

else:
    print("Pas assez de données pour effectuer la validation.")

# ============================================================
# EXPORT
# ============================================================

results.to_csv(
    "v43_global_results.csv",
    index=False
)

summary.to_csv(
    "v43_walk_forward_results.csv",
    index=False
)

print("\nFichiers créés :")
print("  v43_global_results.csv")
print("  v43_walk_forward_results.csv")

print("\n" + "=" * 75)
print("FIN V4.3")
print("=" * 75)