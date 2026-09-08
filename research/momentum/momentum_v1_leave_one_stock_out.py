import pandas as pd
import numpy as np
from pathlib import Path

TRADES_FILE = Path("results/momentum/momentum_portfolio_v5_1_costs_trades_3d.csv")
OUTPUT_FILE = Path("results/momentum/momentum_v1_leave_one_stock_out_3d.csv")

INITIAL_CAPITAL = 10000.0

df = pd.read_csv(TRADES_FILE)

df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")
df["Return_pct"] = pd.to_numeric(df["Return_pct"], errors="coerce")
df["Ticker"] = df["Ticker"].astype(str)

df = df.dropna(subset=["PnL", "Ticker"]).copy()

print("=" * 90)
print("MOMENTUM V1 - LEAVE-ONE-STOCK-OUT")
print("HOLD 3 JOURS - V5.1")
print("=" * 90)

print(f"\nTrades totaux : {len(df)}")
print(f"PnL total     : ${df['PnL'].sum():,.2f}")
print(f"Actions       : {df['Ticker'].nunique()}")

def stats(data):
    pnl = data["PnL"]
    total_pnl = pnl.sum()
    final_equity = INITIAL_CAPITAL + total_pnl
    ret = total_pnl / INITIAL_CAPITAL * 100

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    win_rate = (pnl > 0).mean() * 100

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    pf = gross_profit / gross_loss if gross_loss > 0 else np.nan

    return {
        "Trades": len(data),
        "PnL": total_pnl,
        "Return_pct": ret,
        "Win_Rate": win_rate,
        "Profit_Factor": pf,
        "Avg_PnL": pnl.mean(),
        "Median_PnL": pnl.median(),
    }

# ============================================================
# 1. BASELINE
# ============================================================

base = stats(df)

print("\n" + "=" * 90)
print("1. BASELINE")
print("=" * 90)

print(f"Trades       : {base['Trades']}")
print(f"PnL          : ${base['PnL']:,.2f}")
print(f"Return       : {base['Return_pct']:.2f}%")
print(f"Win Rate     : {base['Win_Rate']:.2f}%")
print(f"Profit Factor: {base['Profit_Factor']:.2f}")
print(f"Avg trade    : ${base['Avg_PnL']:.2f}")
print(f"Median trade : ${base['Median_PnL']:.2f}")

# ============================================================
# 2. LEAVE ONE STOCK OUT
# ============================================================

results = []

for ticker in sorted(df["Ticker"].unique()):

    test = df[df["Ticker"] != ticker]

    s = stats(test)

    results.append({
        "Removed": ticker,
        **s,
        "PnL_vs_baseline_pct": s["PnL"] / base["PnL"] * 100,
        "PnL_change_pct": (s["PnL"] - base["PnL"]) / abs(base["PnL"]) * 100,
    })

results_df = pd.DataFrame(results)

# Trier par PnL restant
results_df = results_df.sort_values("PnL", ascending=False)

print("\n" + "=" * 90)
print("2. LEAVE-ONE-STOCK-OUT")
print("=" * 90)

print(
    results_df[
        [
            "Removed",
            "Trades",
            "PnL",
            "Return_pct",
            "Win_Rate",
            "Profit_Factor",
            "PnL_vs_baseline_pct",
        ]
    ].to_string(
        index=False,
        formatters={
            "PnL": lambda x: f"${x:,.2f}",
            "Return_pct": lambda x: f"{x:.2f}%",
            "Win_Rate": lambda x: f"{x:.2f}%",
            "Profit_Factor": lambda x: f"{x:.2f}",
            "PnL_vs_baseline_pct": lambda x: f"{x:.2f}%",
        },
    )
)

# ============================================================
# 3. TOP 4 REMOVAL
# ============================================================

top4 = ["TSLA", "AMD", "NVDA", "AVGO"]

test_top4_removed = df[~df["Ticker"].isin(top4)]
s_top4 = stats(test_top4_removed)

print("\n" + "=" * 90)
print("3. SANS TSLA + AMD + NVDA + AVGO")
print("=" * 90)

print(f"Trades       : {s_top4['Trades']}")
print(f"PnL          : ${s_top4['PnL']:,.2f}")
print(f"Return       : {s_top4['Return_pct']:.2f}%")
print(f"Win Rate     : {s_top4['Win_Rate']:.2f}%")
print(f"Profit Factor: {s_top4['Profit_Factor']:.2f}")
print(f"Avg trade    : ${s_top4['Avg_PnL']:.2f}")
print(f"Median trade : ${s_top4['Median_PnL']:.2f}")

# ============================================================
# 4. TOP 5 CONTRIBUTORS
# ============================================================

ticker_pnl = (
    df.groupby("Ticker")["PnL"]
    .sum()
    .sort_values(ascending=False)
)

top5 = ticker_pnl.head(5).index.tolist()

test_top5_removed = df[~df["Ticker"].isin(top5)]
s_top5 = stats(test_top5_removed)

print("\n" + "=" * 90)
print("4. SANS TOP 5 CONTRIBUTEURS")
print("=" * 90)

print(f"Actions retirées : {', '.join(top5)}")
print(f"Trades           : {s_top5['Trades']}")
print(f"PnL              : ${s_top5['PnL']:,.2f}")
print(f"Return           : {s_top5['Return_pct']:.2f}%")
print(f"Win Rate         : {s_top5['Win_Rate']:.2f}%")
print(f"Profit Factor    : {s_top5['Profit_Factor']:.2f}")

# ============================================================
# 5. PNL ANNUEL SANS TOP 4
# ============================================================

if "Exit_Date" in test_top4_removed.columns:

    test_top4_removed["Exit_Date"] = pd.to_datetime(
        test_top4_removed["Exit_Date"],
        errors="coerce"
    )

    test_top4_removed["Exit_Year"] = (
        test_top4_removed["Exit_Date"].dt.year
    )

    annual = (
        test_top4_removed
        .groupby("Exit_Year")["PnL"]
        .agg(["count", "sum", "mean"])
    )

    print("\n" + "=" * 90)
    print("5. PNL ANNUEL SANS LES 4 GROS CONTRIBUTEURS")
    print("=" * 90)

    print(
        annual.to_string(
            formatters={
                "sum": lambda x: f"${x:,.2f}",
                "mean": lambda x: f"${x:.2f}",
            }
        )
    )

# ============================================================
# 6. TOP 10 CONTRIBUTORS
# ============================================================

print("\n" + "=" * 90)
print("6. TOP 10 CONTRIBUTEURS")
print("=" * 90)

top10 = ticker_pnl.head(10)

for ticker, pnl in top10.items():
    contribution = pnl / base["PnL"] * 100
    print(f"{ticker:5s} : ${pnl:10,.2f}  ({contribution:6.2f}%)")

# ============================================================
# 7. SAUVEGARDE
# ============================================================

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
results_df.to_csv(OUTPUT_FILE, index=False)

print("\n" + "=" * 90)
print("ANALYSE TERMINEE")
print("=" * 90)
print(f"Résultat sauvegardé dans : {OUTPUT_FILE}")
