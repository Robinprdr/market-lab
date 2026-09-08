import pandas as pd
import numpy as np
from pathlib import Path

TRADES_FILE = Path(
    "results/momentum/momentum_portfolio_v5_1_costs_trades_3d.csv"
)

RESEARCH_FILE = Path(
    "results/momentum/momentum_v1_research.csv"
)

OUTPUT_FILE = Path(
    "results/momentum/momentum_v1_market_regime_3d.csv"
)

print("=" * 90)
print("MOMENTUM V1 - ANALYSE DES RÉGIMES DE MARCHÉ")
print("HOLD 3 JOURS - V5.1 - VERSION CORRIGÉE")
print("=" * 90)


# ============================================================
# 1. CHARGEMENT
# ============================================================

trades = pd.read_csv(TRADES_FILE)
research = pd.read_csv(RESEARCH_FILE)

trades["Entry_Date"] = pd.to_datetime(
    trades["Entry_Date"],
    errors="coerce"
)

research["Date"] = pd.to_datetime(
    research["Date"],
    errors="coerce"
)

print("\nDates trades :")
print(
    f"  {trades['Entry_Date'].min().date()} "
    f"-> {trades['Entry_Date'].max().date()}"
)

print("\nDataset recherche :")
print(f"  Lignes : {len(research):,}")
print(f"  Tickers : {research['Ticker'].nunique()}")


# ============================================================
# 2. VÉRIFICATION DES FACTEURS SPY
# ============================================================

spy_columns = [
    "SPY_Return_1D",
    "SPY_Return_5D",
    "SPY_Return_10D",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio",
]

print("\n" + "=" * 90)
print("1. VÉRIFICATION DES DONNÉES SPY")
print("=" * 90)

for column in spy_columns:

    if column not in research.columns:
        raise ValueError(
            f"Colonne absente du dataset : {column}"
        )

    valid = research[column].notna().sum()

    print(
        f"  {column:<24} "
        f"{valid:,} valeurs valides"
    )


# ============================================================
# 3. CONSTRUCTION D'UNE TABLE SPY PAR DATE
# ============================================================

print("\nConstruction du marché SPY par date...")

spy = research[
    [
        "Date",
        "SPY_Return_1D",
        "SPY_Return_5D",
        "SPY_Return_10D",
        "SPY_Distance_SMA50",
        "SPY_Volume_Ratio",
    ]
].copy()

spy = spy.dropna(
    subset=["Date", "SPY_Return_10D"]
)

# Une seule observation SPY par date.
# Les mêmes valeurs SPY sont répétées sur les 47 actions,
# donc on garde simplement la première.

spy = (
    spy
    .sort_values("Date")
    .drop_duplicates(subset=["Date"])
    .reset_index(drop=True)
)

print(f"  Dates SPY disponibles : {len(spy):,}")
print(
    f"  Période : "
    f"{spy['Date'].min().date()} "
    f"-> {spy['Date'].max().date()}"
)


# ============================================================
# 4. QUARTILES SPY RETURN 10D
# ============================================================

q25 = spy["SPY_Return_10D"].quantile(0.25)
q50 = spy["SPY_Return_10D"].quantile(0.50)
q75 = spy["SPY_Return_10D"].quantile(0.75)

print("\n" + "=" * 90)
print("2. QUARTILES SPY RETURN_10D")
print("=" * 90)

print(f"Q25 : {q25:.4%}")
print(f"Q50 : {q50:.4%}")
print(f"Q75 : {q75:.4%}")


# ============================================================
# 5. CLASSIFICATION DES RÉGIMES
# ============================================================

def classify_regime(x):

    if pd.isna(x):
        return np.nan

    if x <= q25:
        return "Q1 - marché faible"

    elif x <= q50:
        return "Q2 - faible/neutre"

    elif x <= q75:
        return "Q3 - neutre/fort"

    else:
        return "Q4 - marché fort"


spy["Regime"] = spy[
    "SPY_Return_10D"
].apply(classify_regime)

print("\nRépartition des régimes :")

print(
    spy["Regime"]
    .value_counts()
    .sort_index()
)


# ============================================================
# 6. MATCHING AVEC LES TRADES
# ============================================================

print("\n" + "=" * 90)
print("3. MATCHING TRADES / SPY")
print("=" * 90)

trades["Date_Key"] = (
    trades["Entry_Date"]
    .dt.normalize()
)

spy["Date_Key"] = (
    spy["Date"]
    .dt.normalize()
)

spy_map = spy[
    [
        "Date_Key",
        "SPY_Return_1D",
        "SPY_Return_5D",
        "SPY_Return_10D",
        "SPY_Distance_SMA50",
        "SPY_Volume_Ratio",
        "Regime",
    ]
].copy()

trades_regime = trades.merge(
    spy_map,
    on="Date_Key",
    how="left"
)

matched = trades_regime["Regime"].notna().sum()
unmatched = trades_regime["Regime"].isna().sum()

print(f"Trades total       : {len(trades_regime):,}")
print(f"Trades avec SPY    : {matched:,}")
print(f"Trades sans SPY    : {unmatched:,}")

if len(trades_regime) > 0:

    print(
        f"Matching           : "
        f"{matched / len(trades_regime):.2%}"
    )

if matched == 0:

    raise ValueError(
        "Aucun trade ne correspond aux dates SPY."
    )


# ============================================================
# 7. FONCTION PERFORMANCE
# ============================================================

def performance(group):

    pnl = pd.to_numeric(
        group["PnL"],
        errors="coerce"
    ).dropna()

    if len(pnl) == 0:

        return pd.Series({
            "Trades": 0,
            "PnL": 0.0,
            "Avg_PnL": 0.0,
            "Win_Rate": np.nan,
            "Profit_Factor": np.nan,
        })

    gross_profit = pnl[pnl > 0].sum()

    gross_loss = -pnl[pnl < 0].sum()

    if gross_loss > 0:

        pf = gross_profit / gross_loss

    else:

        pf = np.inf

    return pd.Series({
        "Trades": len(pnl),
        "PnL": pnl.sum(),
        "Avg_PnL": pnl.mean(),
        "Win_Rate": (pnl > 0).mean(),
        "Profit_Factor": pf,
    })


# ============================================================
# 8. PERFORMANCE PAR RÉGIME
# ============================================================

print("\n" + "=" * 90)
print("4. PERFORMANCE SELON LE RÉGIME DU SPY")
print("=" * 90)

regime_perf = (
    trades_regime
    .dropna(subset=["Regime"])
    .groupby("Regime")
    .apply(
        performance,
        include_groups=False
    )
    .reset_index()
)

regime_order = [
    "Q1 - marché faible",
    "Q2 - faible/neutre",
    "Q3 - neutre/fort",
    "Q4 - marché fort",
]

regime_perf["Regime"] = pd.Categorical(
    regime_perf["Regime"],
    categories=regime_order,
    ordered=True,
)

regime_perf = regime_perf.sort_values(
    "Regime"
)

display_df = regime_perf.copy()

display_df["PnL"] = display_df[
    "PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_df["Avg_PnL"] = display_df[
    "Avg_PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_df["Win_Rate"] = display_df[
    "Win_Rate"
].map(
    lambda x:
    f"{x:.2%}" if pd.notna(x) else "NaN"
)

display_df["Profit_Factor"] = display_df[
    "Profit_Factor"
].map(
    lambda x:
    f"{x:.2f}" if np.isfinite(x) else "inf"
)

print(
    display_df.to_string(
        index=False
    )
)


# ============================================================
# 9. ANNÉE + RÉGIME
# ============================================================

print("\n" + "=" * 90)
print("5. ANNÉE + RÉGIME")
print("=" * 90)

trades_regime["Year"] = (
    trades_regime["Entry_Date"].dt.year
)

year_regime = (
    trades_regime
    .dropna(subset=["Regime"])
    .groupby(
        ["Year", "Regime"]
    )
    .apply(
        performance,
        include_groups=False
    )
    .reset_index()
)

year_regime["Regime"] = pd.Categorical(
    year_regime["Regime"],
    categories=regime_order,
    ordered=True,
)

year_regime = year_regime.sort_values(
    ["Year", "Regime"]
)

display_year = year_regime.copy()

display_year["PnL"] = display_year[
    "PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_year["Avg_PnL"] = display_year[
    "Avg_PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_year["Win_Rate"] = display_year[
    "Win_Rate"
].map(
    lambda x:
    f"{x:.2%}" if pd.notna(x) else "NaN"
)

display_year["Profit_Factor"] = display_year[
    "Profit_Factor"
].map(
    lambda x:
    f"{x:.2f}" if np.isfinite(x) else "inf"
)

print(
    display_year.to_string(
        index=False
    )
)


# ============================================================
# 10. SPY POSITIF / NÉGATIF
# ============================================================

print("\n" + "=" * 90)
print("6. SPY POSITIF / NÉGATIF SUR 10 JOURS")
print("=" * 90)

trades_regime["SPY_Direction"] = np.where(
    trades_regime["SPY_Return_10D"] >= 0,
    "SPY 10D positif",
    "SPY 10D négatif",
)

direction_perf = (
    trades_regime
    .dropna(subset=["SPY_Direction"])
    .groupby("SPY_Direction")
    .apply(
        performance,
        include_groups=False
    )
    .reset_index()
)

display_direction = direction_perf.copy()

display_direction["PnL"] = display_direction[
    "PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_direction["Avg_PnL"] = display_direction[
    "Avg_PnL"
].map(
    lambda x: f"${x:,.2f}"
)

display_direction["Win_Rate"] = display_direction[
    "Win_Rate"
].map(
    lambda x:
    f"{x:.2%}" if pd.notna(x) else "NaN"
)

display_direction["Profit_Factor"] = display_direction[
    "Profit_Factor"
].map(
    lambda x:
    f"{x:.2f}" if np.isfinite(x) else "inf"
)

print(
    display_direction.to_string(
        index=False
    )
)


# ============================================================
# 11. MOIS POSITIFS / NÉGATIFS PAR RÉGIME
# ============================================================

print("\n" + "=" * 90)
print("7. MOIS POSITIFS / NÉGATIFS PAR RÉGIME")
print("=" * 90)

trades_regime["Month"] = (
    trades_regime["Entry_Date"]
    .dt.to_period("M")
)

monthly_regime = (
    trades_regime
    .dropna(subset=["Regime"])
    .groupby(
        ["Month", "Regime"]
    )["PnL"]
    .sum()
    .reset_index()
)

monthly_regime["Positive"] = (
    monthly_regime["PnL"] > 0
)

monthly_summary = (
    monthly_regime
    .groupby("Regime")
    .agg(
        Months=("PnL", "count"),
        Positive_Months=("Positive", "sum"),
        Negative_Months=(
            "Positive",
            lambda x: (~x).sum()
        ),
        Total_PnL=("PnL", "sum"),
    )
    .reset_index()
)

monthly_summary["Positive_Rate"] = (
    monthly_summary["Positive_Months"]
    / monthly_summary["Months"]
)

print(
    monthly_summary.to_string(
        index=False
    )
)


# ============================================================
# 12. SAUVEGARDE
# ============================================================

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)

save_cols = [
    "Entry_Date",
    "Ticker",
    "PnL",
    "Return_Pct",
    "Regime",
    "SPY_Return_10D",
]

save_cols = [
    c
    for c in save_cols
    if c in trades_regime.columns
]

trades_regime[
    save_cols
].to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# 13. DIAGNOSTIC FINAL
# ============================================================

print("\n" + "=" * 90)
print("8. DIAGNOSTIC FINAL")
print("=" * 90)

if matched == len(trades_regime):

    print(
        "✓ 100% des trades ont un régime SPY."
    )

else:

    print(
        f"⚠ {unmatched} trades sans régime SPY."
    )

print(
    "✓ Les régimes sont calculés à partir "
    "de SPY_Return_10D présent dans le dataset."
)

print("\nRésultat sauvegardé dans :")
print(f"  {OUTPUT_FILE}")

print("\n" + "=" * 90)
print("ANALYSE TERMINÉE")
print("=" * 90)
