import pandas as pd
import numpy as np
from pathlib import Path

TRADES_FILE = Path(
    "results/momentum/momentum_portfolio_v5_1_costs_trades_3d.csv"
)

INITIAL_CAPITAL = 10000.0

df = pd.read_csv(TRADES_FILE)

df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])
df["Exit_Date"] = pd.to_datetime(df["Exit_Date"])
df["PnL"] = pd.to_numeric(df["PnL"], errors="coerce")

df = df.dropna(
    subset=["Entry_Date", "Exit_Date", "PnL"]
).copy()

df["Year"] = df["Exit_Date"].dt.year
df["Quarter"] = df["Exit_Date"].dt.to_period("Q").astype(str)
df["Month"] = df["Exit_Date"].dt.to_period("M").astype(str)

print("=" * 90)
print("MOMENTUM V1 - ROBUSTESSE TEMPORELLE")
print("HOLD 3 JOURS - V5.1")
print("=" * 90)

print(f"\nTrades : {len(df)}")
print(f"PnL    : ${df['PnL'].sum():,.2f}")

def stats(data):

    pnl = data["PnL"]

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.nan
    )

    return {
        "Trades": len(data),
        "PnL": pnl.sum(),
        "Avg_PnL": pnl.mean(),
        "Win_Rate": (pnl > 0).mean() * 100,
        "Profit_Factor": pf,
    }

# ============================================================
# 1. PAR ANNÉE
# ============================================================

print("\n" + "=" * 90)
print("1. PERFORMANCE PAR ANNÉE")
print("=" * 90)

annual = []

for year, group in df.groupby("Year"):

    s = stats(group)

    annual.append({
        "Year": year,
        **s
    })

annual_df = pd.DataFrame(annual)

print(
    annual_df.to_string(
        index=False,
        formatters={
            "PnL": lambda x: f"${x:,.2f}",
            "Avg_PnL": lambda x: f"${x:.2f}",
            "Win_Rate": lambda x: f"{x:.2f}%",
            "Profit_Factor": lambda x: f"{x:.2f}",
        }
    )
)

# ============================================================
# 2. PAR TRIMESTRE
# ============================================================

print("\n" + "=" * 90)
print("2. PERFORMANCE PAR TRIMESTRE")
print("=" * 90)

quarterly = []

for quarter, group in df.groupby("Quarter"):

    s = stats(group)

    quarterly.append({
        "Quarter": quarter,
        **s
    })

quarterly_df = pd.DataFrame(quarterly)

print(
    quarterly_df.to_string(
        index=False,
        formatters={
            "PnL": lambda x: f"${x:,.2f}",
            "Avg_PnL": lambda x: f"${x:.2f}",
            "Win_Rate": lambda x: f"{x:.2f}%",
            "Profit_Factor": lambda x: f"{x:.2f}",
        }
    )
)

# ============================================================
# 3. PAR MOIS
# ============================================================

print("\n" + "=" * 90)
print("3. PERFORMANCE PAR MOIS")
print("=" * 90)

monthly = []

for month, group in df.groupby("Month"):

    s = stats(group)

    monthly.append({
        "Month": month,
        **s
    })

monthly_df = pd.DataFrame(monthly)

print(
    monthly_df.to_string(
        index=False,
        formatters={
            "PnL": lambda x: f"${x:,.2f}",
            "Avg_PnL": lambda x: f"${x:.2f}",
            "Win_Rate": lambda x: f"{x:.2f}%",
            "Profit_Factor": lambda x: f"{x:.2f}",
        }
    )
)

# ============================================================
# 4. MOIS POSITIFS / NÉGATIFS
# ============================================================

positive_months = (monthly_df["PnL"] > 0).sum()
negative_months = (monthly_df["PnL"] < 0).sum()
flat_months = (monthly_df["PnL"] == 0).sum()

print("\n" + "=" * 90)
print("4. MOIS POSITIFS / NÉGATIFS")
print("=" * 90)

print(f"Mois positifs : {positive_months}")
print(f"Mois négatifs : {negative_months}")
print(f"Mois neutres  : {flat_months}")

total_months = len(monthly_df)

if total_months:
    print(
        f"Taux de mois positifs : "
        f"{positive_months / total_months * 100:.2f}%"
    )

# ============================================================
# 5. MEILLEUR / PIRE TRIMESTRE
# ============================================================

print("\n" + "=" * 90)
print("5. MEILLEURS / PIRES TRIMESTRES")
print("=" * 90)

best_q = quarterly_df.loc[
    quarterly_df["PnL"].idxmax()
]

worst_q = quarterly_df.loc[
    quarterly_df["PnL"].idxmin()
]

print(
    f"Meilleur trimestre : "
    f"{best_q['Quarter']} | "
    f"${best_q['PnL']:,.2f}"
)

print(
    f"Pire trimestre     : "
    f"{worst_q['Quarter']} | "
    f"${worst_q['PnL']:,.2f}"
)

# ============================================================
# 6. TRADES GAGNANTS / PERDANTS CONSÉCUTIFS
# ============================================================

print("\n" + "=" * 90)
print("6. SÉQUENCES DE TRADES")
print("=" * 90)

ordered = df.sort_values("Exit_Date").reset_index(drop=True)

max_win_streak = 0
max_loss_streak = 0

current_win = 0
current_loss = 0

for pnl in ordered["PnL"]:

    if pnl > 0:
        current_win += 1
        current_loss = 0
    elif pnl < 0:
        current_loss += 1
        current_win = 0
    else:
        current_win = 0
        current_loss = 0

    max_win_streak = max(
        max_win_streak,
        current_win
    )

    max_loss_streak = max(
        max_loss_streak,
        current_loss
    )

print(f"Plus longue série gagnante : {max_win_streak}")
print(f"Plus longue série perdante  : {max_loss_streak}")

# ============================================================
# 7. PLUS LONGUE PÉRIODE DE PNL NÉGATIF
# ============================================================

monthly_ordered = monthly_df.sort_values("Month")

max_negative_months = 0
current_negative_months = 0

for pnl in monthly_ordered["PnL"]:

    if pnl < 0:
        current_negative_months += 1
    else:
        current_negative_months = 0

    max_negative_months = max(
        max_negative_months,
        current_negative_months
    )

print(
    f"Plus longue série de mois négatifs : "
    f"{max_negative_months}"
)

# ============================================================
# 8. DISTRIBUTION PAR ANNÉE
# ============================================================

print("\n" + "=" * 90)
print("8. ANNÉES POSITIVES / NÉGATIVES")
print("=" * 90)

positive_years = (annual_df["PnL"] > 0).sum()
negative_years = (annual_df["PnL"] < 0).sum()

print(f"Années positives : {positive_years}")
print(f"Années négatives : {negative_years}")

# ============================================================
# 9. SAUVEGARDE
# ============================================================

output = Path(
    "results/momentum/momentum_v1_time_robustness_3d.csv"
)

output.parent.mkdir(
    parents=True,
    exist_ok=True
)

quarterly_df.to_csv(
    output,
    index=False
)

print("\n" + "=" * 90)
print("ANALYSE TERMINÉE")
print("=" * 90)

print(
    f"Résultat sauvegardé dans : {output}"
)
