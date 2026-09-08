import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path(
    "results/momentum/"
    "momentum_portfolio_v5_1_costs_trades_3d.csv"
)

OUTPUT_FILE = Path(
    "results/momentum/"
    "momentum_v1_pnl_concentration_3d.csv"
)

print("=" * 90)
print("MOMENTUM V1 - ANALYSE DE CONCENTRATION DU PNL")
print("HOLD 3 JOURS - V5.1")
print("=" * 90)

df = pd.read_csv(INPUT_FILE)

df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])
df["Exit_Date"] = pd.to_datetime(df["Exit_Date"])

df = df.sort_values(
    "PnL",
    ascending=False
).reset_index(drop=True)

total_pnl = df["PnL"].sum()
total_trades = len(df)

print()
print(f"Trades analysés : {total_trades:,}")
print(f"PnL total       : ${total_pnl:,.2f}")

# ============================================================
# 1. STATISTIQUES GENERALES
# ============================================================

print()
print("=" * 90)
print("1. STATISTIQUES GENERALES")
print("=" * 90)

print(
    f"Trade moyen    : "
    f"${df['PnL'].mean():,.2f}"
)

print(
    f"Trade médian   : "
    f"${df['PnL'].median():,.2f}"
)

print(
    f"Meilleur trade : "
    f"${df['PnL'].max():,.2f}"
)

print(
    f"Pire trade     : "
    f"${df['PnL'].min():,.2f}"
)

print(
    f"Écart-type PnL : "
    f"${df['PnL'].std():,.2f}"
)

# ============================================================
# 2. CONCENTRATION PAR ACTION
# ============================================================

print()
print("=" * 90)
print("2. PNL PAR ACTION")
print("=" * 90)

by_ticker = (
    df.groupby("Ticker")
    .agg(
        Trades=("PnL", "count"),
        PnL=("PnL", "sum"),
        Avg_PnL=("PnL", "mean"),
        Win_Rate=("PnL", lambda x: (x > 0).mean() * 100),
    )
    .sort_values("PnL", ascending=False)
)

by_ticker["Contribution_pct"] = (
    by_ticker["PnL"]
    / total_pnl
    * 100
)

print(
    by_ticker.to_string(
        float_format=lambda x: f"{x:,.2f}"
    )
)

# ============================================================
# 3. TOP ACTIONS
# ============================================================

print()
print("=" * 90)
print("3. CONCENTRATION DU PNL - TOP ACTIONS")
print("=" * 90)

for n in [1, 3, 5, 10]:

    top_pnl = (
        by_ticker
        .head(n)["PnL"]
        .sum()
    )

    contribution = (
        top_pnl
        / total_pnl
        * 100
    )

    print(
        f"Top {n:>2} actions : "
        f"${top_pnl:,.2f} "
        f"({contribution:.2f}% du PnL)"
    )

# ============================================================
# 4. TOP TRADES
# ============================================================

print()
print("=" * 90)
print("4. MEILLEURS TRADES")
print("=" * 90)

top10 = df.head(10)[
    [
        "Ticker",
        "Entry_Date",
        "Exit_Date",
        "Return_pct",
        "PnL",
        "Holding_Days",
    ]
]

print(
    top10.to_string(
        index=False,
        float_format=lambda x: f"{x:,.3f}"
    )
)

# ============================================================
# 5. PIRE TRADES
# ============================================================

print()
print("=" * 90)
print("5. PIRES TRADES")
print("=" * 90)

bottom10 = df.tail(10).sort_values(
    "PnL",
    ascending=True
)[
    [
        "Ticker",
        "Entry_Date",
        "Exit_Date",
        "Return_pct",
        "PnL",
        "Holding_Days",
    ]
]

print(
    bottom10.to_string(
        index=False,
        float_format=lambda x: f"{x:,.3f}"
    )
)

# ============================================================
# 6. IMPACT DES MEILLEURS TRADES
# ============================================================

print()
print("=" * 90)
print("6. TEST SANS LES MEILLEURS TRADES")
print("=" * 90)

for pct in [1, 5, 10, 20]:

    n_remove = max(
        1,
        int(len(df) * pct / 100)
    )

    pnl_without = (
        df.iloc[n_remove:]["PnL"].sum()
    )

    remaining_trades = (
        len(df) - n_remove
    )

    print(
        f"Sans top {pct:>2}% "
        f"({n_remove:>3} trades) : "
        f"PnL = ${pnl_without:,.2f} "
        f"| Trades restants = {remaining_trades:,}"
    )

# ============================================================
# 7. IMPACT DES PIRES TRADES
# ============================================================

print()
print("=" * 90)
print("7. TEST SANS LES PIRES TRADES")
print("=" * 90)

df_ascending = df.sort_values(
    "PnL",
    ascending=True
).reset_index(drop=True)

for pct in [1, 5, 10]:

    n_remove = max(
        1,
        int(len(df) * pct / 100)
    )

    pnl_without = (
        df_ascending.iloc[n_remove:]["PnL"].sum()
    )

    print(
        f"Sans pire {pct:>2}% "
        f"({n_remove:>3} trades) : "
        f"PnL = ${pnl_without:,.2f}"
    )

# ============================================================
# 8. PNL PAR ANNEE
# ============================================================

print()
print("=" * 90)
print("8. PNL PAR ANNEE")
print("=" * 90)

df["Exit_Year"] = (
    df["Exit_Date"]
    .dt.year
)

by_year = (
    df.groupby("Exit_Year")
    .agg(
        Trades=("PnL", "count"),
        PnL=("PnL", "sum"),
        Avg_PnL=("PnL", "mean"),
        Win_Rate=("PnL", lambda x: (x > 0).mean() * 100),
    )
)

by_year["Contribution_pct"] = (
    by_year["PnL"]
    / total_pnl
    * 100
)

print(
    by_year.to_string(
        float_format=lambda x: f"{x:,.2f}"
    )
)

# ============================================================
# 9. PNL CUMULE PAR ACTION
# ============================================================

print()
print("=" * 90)
print("9. ACTIONS POSITIVES / NEGATIVES")
print("=" * 90)

positive_tickers = (
    by_ticker["PnL"] > 0
).sum()

negative_tickers = (
    by_ticker["PnL"] < 0
).sum()

print(
    f"Actions avec PnL positif : "
    f"{positive_tickers}"
)

print(
    f"Actions avec PnL négatif  : "
    f"{negative_tickers}"
)

# ============================================================
# 10. CONCENTRATION DES PROFITS
# ============================================================

print()
print("=" * 90)
print("10. CONCENTRATION DES PROFITS")
print("=" * 90)

winning_trades = df[
    df["PnL"] > 0
].copy()

losing_trades = df[
    df["PnL"] < 0
].copy()

gross_profit = (
    winning_trades["PnL"].sum()
)

gross_loss = abs(
    losing_trades["PnL"].sum()
)

print(
    f"Gross profit : "
    f"${gross_profit:,.2f}"
)

print(
    f"Gross loss   : "
    f"${gross_loss:,.2f}"
)

print(
    f"Profit factor: "
    f"{gross_profit / gross_loss:.2f}"
)

# ============================================================
# 11. DISTRIBUTION DES TRADES
# ============================================================

print()
print("=" * 90)
print("11. DISTRIBUTION DES TRADES")
print("=" * 90)

for threshold in [
    -2.0,
    -1.0,
    0.0,
    1.0,
    2.0,
    3.0,
]:

    count = (
        df["Return_pct"] >= threshold
    ).sum()

    pct = (
        count
        / len(df)
        * 100
    )

    print(
        f"Trades >= {threshold:+.1f}% : "
        f"{count:>4} "
        f"({pct:.2f}%)"
    )

# ============================================================
# 12. SAUVEGARDE
# ============================================================

output = by_ticker.reset_index()

output.to_csv(
    OUTPUT_FILE,
    index=False
)

print()
print("=" * 90)
print("ANALYSE TERMINEE")
print("=" * 90)

print(
    f"Résultat sauvegardé dans : "
    f"{OUTPUT_FILE}"
)

print("=" * 90)
