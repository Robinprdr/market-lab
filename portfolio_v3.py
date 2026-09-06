import pandas as pd
import numpy as np


# ============================================================
# PORTFOLIO V3
# ============================================================

INPUT_FILE = "strategy_v1_scored_trades.csv"

INITIAL_CAPITAL = 10_000.0
ALLOCATION = 0.20
MAX_POSITIONS = 5

MIN_SCORE = 4


# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

df = pd.read_csv(INPUT_FILE)

required_columns = [
    "Ticker",
    "Score",
    "PnL_Pct",
]

for column in required_columns:
    if column not in df.columns:
        raise ValueError(f"Colonne manquante : {column}")


# ============================================================
# DATES
# ============================================================

if "Entry_Date" in df.columns:
    df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])
elif "Date" in df.columns:
    df["Entry_Date"] = pd.to_datetime(df["Date"])
else:
    raise ValueError("Aucune colonne Entry_Date ou Date trouvée.")


if "Exit_Date" in df.columns:
    df["Exit_Date"] = pd.to_datetime(df["Exit_Date"])
else:
    df["Exit_Date"] = pd.NaT


# Si Exit_Date manque, on utilise Holding_Days
missing_exit = df["Exit_Date"].isna()

if missing_exit.any():

    if "Holding_Days" in df.columns:
        holding_days = (
            df.loc[missing_exit, "Holding_Days"]
            .fillna(5)
        )
    else:
        holding_days = 5

    df.loc[missing_exit, "Exit_Date"] = (
        df.loc[missing_exit, "Entry_Date"]
        + pd.to_timedelta(holding_days, unit="D")
    )


# ============================================================
# FILTRE SCORE
# ============================================================

df = df[df["Score"] >= MIN_SCORE].copy()

df = df.sort_values(
    ["Entry_Date", "Score", "Ticker"],
    ascending=[True, False, True]
).reset_index(drop=True)


print("=" * 70)
print("PORTFOLIO V3")
print("=" * 70)
print()

print(f"Trades candidats : {len(df)}")
print(f"Score minimum    : {MIN_SCORE}")
print(f"Capital initial  : ${INITIAL_CAPITAL:,.2f}")
print(f"Allocation       : {ALLOCATION:.0%}")
print(f"Max positions    : {MAX_POSITIONS}")
print()


# ============================================================
# BACKTEST
# ============================================================

cash = INITIAL_CAPITAL

open_positions = []
closed_trades = []
equity_history = []

all_dates = pd.date_range(
    start=df["Entry_Date"].min(),
    end=df["Exit_Date"].max(),
    freq="D"
)

trade_id = 0


for current_date in all_dates:

    # ========================================================
    # 1. FERMETURE DES POSITIONS
    # ========================================================

    still_open = []

    for position in open_positions:

        if position["exit_date"] <= current_date:

            exit_value = (
                position["capital"]
                * (1 + position["pnl_pct"])
            )

            cash += exit_value

            position["exit_value"] = exit_value
            position["closed_date"] = current_date

            closed_trades.append(position)

        else:
            still_open.append(position)

    open_positions = still_open


    # ========================================================
    # 2. SIGNALS DU JOUR
    # ========================================================

    todays_signals = df[
        df["Entry_Date"] == current_date
    ].copy()


    # ========================================================
    # 3. TRI PAR SCORE
    # ========================================================

    if len(todays_signals) > 0:

        todays_signals = todays_signals.sort_values(
            ["Score", "Ticker"],
            ascending=[False, True]
        )


        for _, signal in todays_signals.iterrows():

            # Maximum 5 positions
            if len(open_positions) >= MAX_POSITIONS:
                break


            ticker = signal["Ticker"]


            # Une seule position par entreprise
            already_open = any(
                position["ticker"] == ticker
                for position in open_positions
            )

            if already_open:
                continue


            # =================================================
            # EQUITY DISPONIBLE
            # =================================================

            current_equity = (
                cash
                + sum(
                    position["capital"]
                    for position in open_positions
                )
            )


            # Taille de position
            position_size = (
                current_equity * ALLOCATION
            )


            # Impossible d'investir plus que le cash disponible
            if position_size > cash:
                continue


            cash -= position_size

            trade_id += 1


            position = {
                "trade_id": trade_id,
                "ticker": ticker,
                "entry_date": current_date,
                "exit_date": signal["Exit_Date"],
                "score": int(signal["Score"]),
                "pnl_pct": float(signal["PnL_Pct"]),
                "capital": position_size,
            }


            open_positions.append(position)


    # ========================================================
    # 4. EQUITY
    # ========================================================

    # Pour une position encore ouverte, on ne connaît pas encore
    # son résultat final.
    #
    # On valorise donc temporairement la position à son capital
    # initial. Le résultat réel est ajouté uniquement à la sortie.

    open_value = sum(
        position["capital"]
        for position in open_positions
    )

    equity = cash + open_value


    equity_history.append({
        "Date": current_date,
        "Cash": cash,
        "Open_Positions": len(open_positions),
        "Equity": equity,
    })


# ============================================================
# FERMETURE DES DERNIÈRES POSITIONS
# ============================================================

for position in open_positions:

    exit_value = (
        position["capital"]
        * (1 + position["pnl_pct"])
    )

    cash += exit_value

    position["exit_value"] = exit_value
    position["closed_date"] = all_dates.max()

    closed_trades.append(position)


final_equity = cash


# ============================================================
# DATAFRAMES
# ============================================================

trades_df = pd.DataFrame(closed_trades)

equity_df = pd.DataFrame(equity_history)


if trades_df.empty:
    raise ValueError("Aucun trade exécuté.")


# ============================================================
# COURBE DE CAPITAL
# ============================================================

equity_df["Daily_Return"] = (
    equity_df["Equity"].pct_change()
)

equity_df["Peak"] = (
    equity_df["Equity"].cummax()
)

equity_df["Drawdown"] = (
    equity_df["Equity"]
    / equity_df["Peak"]
    - 1
)


# ============================================================
# STATISTIQUES
# ============================================================

pnl = trades_df["pnl_pct"]


wins = pnl[pnl > 0]
losses = pnl[pnl <= 0]


win_rate = (
    (pnl > 0).mean()
)


average_pnl = pnl.mean()

median_pnl = pnl.median()


gross_profit = wins.sum()

gross_loss = abs(losses.sum())


if gross_loss > 0:
    profit_factor = (
        gross_profit / gross_loss
    )
else:
    profit_factor = np.inf


# Expectancy basée sur une position de 20%
expectancy = (
    pnl.mean()
    * INITIAL_CAPITAL
    * ALLOCATION
)


max_drawdown = (
    equity_df["Drawdown"].min()
)


daily_returns = (
    equity_df["Daily_Return"]
    .dropna()
)


if (
    len(daily_returns) > 1
    and daily_returns.std() > 0
):

    sharpe = (
        daily_returns.mean()
        / daily_returns.std()
        * np.sqrt(252)
    )

else:

    sharpe = 0.0


# ============================================================
# RENDEMENT
# ============================================================

total_return = (
    final_equity
    / INITIAL_CAPITAL
    - 1
)


days = (
    equity_df["Date"].iloc[-1]
    - equity_df["Date"].iloc[0]
).days


years = days / 365.25


if years > 0:

    cagr = (
        final_equity
        / INITIAL_CAPITAL
    ) ** (1 / years) - 1

else:

    cagr = 0.0


# ============================================================
# AFFICHAGE
# ============================================================

print("=" * 70)
print("RÉSULTATS V3")
print("=" * 70)
print()

print(f"Capital final      : ${final_equity:,.2f}")
print(f"Rendement total    : {total_return:.2%}")
print(f"CAGR               : {cagr:.2%}")
print(f"Trades             : {len(trades_df)}")
print(f"Win rate           : {win_rate:.1%}")
print(f"PnL moyen          : {average_pnl:.3%}")
print(f"Médiane            : {median_pnl:.3%}")
print(f"Profit Factor      : {profit_factor:.2f}")
print(f"Expectancy         : ${expectancy:.2f}")
print(f"Max Drawdown       : {max_drawdown:.2%}")
print(f"Sharpe             : {sharpe:.2f}")
print()


# ============================================================
# PERFORMANCE PAR SCORE
# ============================================================

score_stats = (
    trades_df
    .groupby("score")
    .agg(
        Trades=("pnl_pct", "count"),
        Win_Rate=(
            "pnl_pct",
            lambda x: (x > 0).mean()
        ),
        Avg_PnL=("pnl_pct", "mean"),
        Median_PnL=("pnl_pct", "median"),
        Total_PnL=("pnl_pct", "sum"),
    )
    .reset_index()
)


print("=" * 70)
print("PERFORMANCE PAR SCORE")
print("=" * 70)
print()

print(
    score_stats.to_string(index=False)
)

print()


# ============================================================
# PERFORMANCE ANNUELLE
# ============================================================

trades_df["Year"] = (
    pd.to_datetime(
        trades_df["entry_date"]
    ).dt.year
)


annual_stats = (
    trades_df
    .groupby("Year")
    .agg(
        Trades=("pnl_pct", "count"),
        Win_Rate=(
            "pnl_pct",
            lambda x: (x > 0).mean()
        ),
        Avg_PnL=("pnl_pct", "mean"),
        Total_PnL=("pnl_pct", "sum"),
    )
    .reset_index()
)


print("=" * 70)
print("PERFORMANCE ANNUELLE")
print("=" * 70)
print()

print(
    annual_stats.to_string(index=False)
)

print()


# ============================================================
# PERFORMANCE PAR ACTION
# ============================================================

ticker_stats = (
    trades_df
    .groupby("ticker")
    .agg(
        Trades=("pnl_pct", "count"),
        Win_Rate=(
            "pnl_pct",
            lambda x: (x > 0).mean()
        ),
        Avg_PnL=("pnl_pct", "mean"),
        Total_PnL=("pnl_pct", "sum"),
    )
    .sort_values(
        "Total_PnL",
        ascending=False
    )
)


print("=" * 70)
print("TOP 10 ACTIONS")
print("=" * 70)
print()

print(
    ticker_stats.head(10).to_string()
)

print()


# ============================================================
# EXPORT METRICS
# ============================================================

metrics = pd.DataFrame([{

    "Strategy": "SCORE_4",

    "Initial_Capital":
        INITIAL_CAPITAL,

    "Final_Equity":
        final_equity,

    "Total_Return":
        total_return,

    "CAGR":
        cagr,

    "Trades":
        len(trades_df),

    "Win_Rate":
        win_rate,

    "Average_PnL":
        average_pnl,

    "Median_PnL":
        median_pnl,

    "Profit_Factor":
        profit_factor,

    "Expectancy":
        expectancy,

    "Max_Drawdown":
        max_drawdown,

    "Sharpe":
        sharpe,

}])


metrics.to_csv(
    "portfolio_v3_metrics.csv",
    index=False
)


trades_df.to_csv(
    "portfolio_v3_trades.csv",
    index=False
)


equity_df.to_csv(
    "portfolio_v3_equity.csv",
    index=False
)


# ============================================================
# FIN
# ============================================================

print("=" * 70)
print("FICHIERS CRÉÉS")
print("=" * 70)
print()

print("✓ portfolio_v3_metrics.csv")
print("✓ portfolio_v3_trades.csv")
print("✓ portfolio_v3_equity.csv")

print()
print("Backtest V3 terminé.")