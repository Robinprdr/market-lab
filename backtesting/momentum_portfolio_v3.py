import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")

INITIAL_CAPITAL = 10_000.0

# Pour cette phase : contrainte expérimentale.
# Le bot final aura un nombre de positions dynamique.
MAX_POSITIONS = 5

# Allocation maximale par position.
POSITION_SIZE = 0.20

# Momentum V1
ATR_QUANTILE = 0.80
RETURN10_QUANTILE = 0.80

# Horizons à comparer
HOLD_DAYS = [1, 3, 5]

START_DATE = "2022-01-01"
END_DATE = "2025-12-05"


def calculate_threshold(train, column, quantile=0.80):
    return train[column].quantile(quantile)


def mark_to_market(position, row):
    """
    Valeur actuelle d'une position au prix de clôture.
    """
    return position["shares"] * row["Close"]


def run_backtest(df, hold_days):

    capital = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL

    positions = []
    closed_trades = []
    equity_curve = []

    dates = sorted(df["Date"].unique())

    for current_date in dates:

        day = df[df["Date"] == current_date]

        # -----------------------------------------------------
        # 1. GESTION DES POSITIONS EXISTANTES
        # -----------------------------------------------------

        positions_to_close = []

        for position in positions:

            ticker = position["Ticker"]

            row_data = day[day["Ticker"] == ticker]

            if row_data.empty:
                continue

            row = row_data.iloc[0]

            entry_price = position["Entry_Price"]
            entry_date = position["Entry_Date"]

            current_close = row["Close"]

            holding_days = (
                pd.Timestamp(current_date)
                - pd.Timestamp(entry_date)
            ).days

            # Prix théorique actuel
            pnl_pct = (
                current_close / entry_price
                - 1
            )

            # -------------------------------------------------
            # TIME EXIT
            # -------------------------------------------------

            if holding_days >= hold_days:

                exit_price = current_close
                reason = "TIME"

                positions_to_close.append(
                    (position, exit_price, reason)
                )

        # -----------------------------------------------------
        # 2. FERMETURE DES POSITIONS
        # -----------------------------------------------------

        for position, exit_price, reason in positions_to_close:

            if position not in positions:
                continue

            pnl = (
                position["shares"]
                * (exit_price - position["Entry_Price"])
            )

            cash += (
                position["shares"]
                * exit_price
            )

            capital += pnl

            closed_trades.append({
                "Ticker": position["Ticker"],
                "Entry_Date": position["Entry_Date"],
                "Exit_Date": current_date,
                "Entry_Price": position["Entry_Price"],
                "Exit_Price": exit_price,
                "Shares": position["shares"],
                "PnL": pnl,
                "Return_pct": (
                    exit_price / position["Entry_Price"]
                    - 1
                ) * 100,
                "Holding_Days": holding_days,
                "Exit_Reason": reason,
            })

            positions.remove(position)

        # -----------------------------------------------------
        # 3. SIGNALS DU JOUR
        # -----------------------------------------------------

        if len(positions) >= MAX_POSITIONS:
            pass

        else:

            # -------------------------------------------------
            # Seuils walk-forward :
            # le train se termine avant l'année courante.
            # -------------------------------------------------

            year = pd.Timestamp(current_date).year

            if year == 2022:
                train_end = "2021-12-31"
            elif year == 2023:
                train_end = "2022-12-30"
            elif year == 2024:
                train_end = "2023-12-29"
            elif year == 2025:
                train_end = "2024-12-31"
            else:
                train_end = None

            if train_end is not None:

                train = df[
                    df["Date"] <= train_end
                ]

                atr_threshold = calculate_threshold(
                    train,
                    "ATR_Pct",
                    ATR_QUANTILE
                )

                return10_threshold = calculate_threshold(
                    train,
                    "Return_10D",
                    RETURN10_QUANTILE
                )

                # -------------------------------------------------
                # Signaux du jour
                # -------------------------------------------------

                signals = day[
                    (day["ATR_Pct"] >= atr_threshold)
                    &
                    (day["Return_10D"] >= return10_threshold)
                ].copy()

                # Exclure les actions déjà détenues
                held_tickers = {
                    p["Ticker"]
                    for p in positions
                }

                signals = signals[
                    ~signals["Ticker"].isin(held_tickers)
                ]

                # -------------------------------------------------
                # Classement :
                # priorité à ATR puis Return10
                #
                # Ce n'est PAS le ranking complexe rejeté.
                # C'est seulement un départage déterministe.
                # -------------------------------------------------

                signals = signals.sort_values(
                    ["ATR_Pct", "Return_10D"],
                    ascending=False
                )

                available_slots = (
                    MAX_POSITIONS
                    - len(positions)
                )

                signals = signals.head(
                    available_slots
                )

                # -------------------------------------------------
                # 4. ENTRÉE À L'OPEN DU JOUR
                # -------------------------------------------------

                for _, signal in signals.iterrows():

                    entry_price = signal["Open"]

                    if not np.isfinite(entry_price):
                        continue

                    # Allocation fixe pour cette expérience.
                    allocation = min(
                        capital * POSITION_SIZE,
                        cash
                    )

                    if allocation <= 0:
                        continue

                    shares = (
                        allocation
                        / entry_price
                    )

                    cash -= allocation

                    positions.append({
                        "Ticker": signal["Ticker"],
                        "Entry_Date": current_date,
                        "Entry_Price": entry_price,
                        "shares": shares,
                        "Allocation": allocation,
                    })

        # -----------------------------------------------------
        # 5. EQUITY JOURNALIÈRE
        # -----------------------------------------------------

        positions_value = 0.0

        for position in positions:

            ticker = position["Ticker"]

            row_data = day[
                day["Ticker"] == ticker
            ]

            if not row_data.empty:
                positions_value += (
                    position["shares"]
                    * row_data.iloc[0]["Close"]
                )

        equity = cash + positions_value

        equity_curve.append({
            "Date": current_date,
            "Equity": equity,
            "Cash": cash,
            "Open_Positions": len(positions),
        })

    # ---------------------------------------------------------
    # 6. LIQUIDATION FINALE
    # ---------------------------------------------------------

    if positions:

        final_date = dates[-1]
        final_day = df[
            df["Date"] == final_date
        ]

        for position in positions:

            row_data = final_day[
                final_day["Ticker"]
                == position["Ticker"]
            ]

            if row_data.empty:
                continue

            exit_price = row_data.iloc[0]["Close"]

            pnl = (
                position["shares"]
                * (
                    exit_price
                    - position["Entry_Price"]
                )
            )

            cash += (
                position["shares"]
                * exit_price
            )

            closed_trades.append({
                "Ticker": position["Ticker"],
                "Entry_Date": position["Entry_Date"],
                "Exit_Date": final_date,
                "Entry_Price": position["Entry_Price"],
                "Exit_Price": exit_price,
                "Shares": position["shares"],
                "PnL": pnl,
                "Return_pct": (
                    exit_price
                    / position["Entry_Price"]
                    - 1
                ) * 100,
                "Holding_Days": (
                    pd.Timestamp(final_date)
                    - pd.Timestamp(position["Entry_Date"])
                ).days,
                "Exit_Reason": "FINAL",
            })

        positions = []

    trades = pd.DataFrame(closed_trades)
    equity_df = pd.DataFrame(equity_curve)

    if equity_df.empty:
        return trades, equity_df

    # ---------------------------------------------------------
    # MAX DRAWDOWN
    # ---------------------------------------------------------

    equity_df["Peak"] = (
        equity_df["Equity"]
        .cummax()
    )

    equity_df["Drawdown_pct"] = (
        equity_df["Equity"]
        / equity_df["Peak"]
        - 1
    ) * 100

    return trades, equity_df


# =============================================================
# MAIN
# =============================================================

print("=" * 90)
print("MOMENTUM V1 - REALISTIC PORTFOLIO TEST V3")
print("=" * 90)

df = pd.read_csv(
    INPUT_FILE,
    parse_dates=["Date"]
)

df = df[
    (df["Date"] >= START_DATE)
    & (df["Date"] <= END_DATE)
].copy()

df = df.sort_values(
    ["Date", "Ticker"]
).reset_index(drop=True)

print(f"Dataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")
print(
    f"Période : "
    f"{df['Date'].min().date()} → "
    f"{df['Date'].max().date()}"
)

all_summaries = []

for hold_days in HOLD_DAYS:

    print()
    print("=" * 90)
    print(f"HOLD {hold_days} JOURS")
    print("=" * 90)

    trades, equity = run_backtest(
        df,
        hold_days
    )

    if trades.empty:
        print("Aucun trade.")
        continue

    final_equity = equity.iloc[-1]["Equity"]

    total_return = (
        final_equity
        / INITIAL_CAPITAL
        - 1
    ) * 100

    win_rate = (
        trades["PnL"] > 0
    ).mean() * 100

    avg_trade = (
        trades["Return_pct"]
        .mean()
    )

    median_trade = (
        trades["Return_pct"]
        .median()
    )

    gross_profit = trades.loc[
        trades["PnL"] > 0,
        "PnL"
    ].sum()

    gross_loss = abs(
        trades.loc[
            trades["PnL"] < 0,
            "PnL"
        ].sum()
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.nan
    )

    max_dd = equity[
        "Drawdown_pct"
    ].min()

    print(f"Trades        : {len(trades):,}")
    print(f"Win rate      : {win_rate:.2f}%")
    print(f"PnL           : ${trades['PnL'].sum():,.2f}")
    print(f"Final equity  : ${final_equity:,.2f}")
    print(f"Return        : {total_return:+.2f}%")
    print(f"Avg trade     : {avg_trade:+.3f}%")
    print(f"Median trade  : {median_trade:+.3f}%")
    print(f"Profit factor : {profit_factor:.2f}")
    print(f"Max drawdown  : {max_dd:+.2f}%")

    print()
    print("Trades par année :")

    trades["Exit_Year"] = pd.to_datetime(
        trades["Exit_Date"]
    ).dt.year

    yearly = trades.groupby(
        "Exit_Year"
    )["PnL"].sum()

    for year, pnl in yearly.items():
        print(
            f"  {year} : "
            f"${pnl:+,.2f}"
        )

    all_summaries.append({
        "Hold_Days": hold_days,
        "Trades": len(trades),
        "Win_Rate_pct": win_rate,
        "PnL": trades["PnL"].sum(),
        "Final_Equity": final_equity,
        "Return_pct": total_return,
        "Avg_Trade_pct": avg_trade,
        "Median_Trade_pct": median_trade,
        "Profit_Factor": profit_factor,
        "Max_Drawdown_pct": max_dd,
    })

    # Sauvegarde détaillée
    trades.to_csv(
        f"results/momentum/momentum_portfolio_v3_trades_{hold_days}d.csv",
        index=False
    )

    equity.to_csv(
        f"results/momentum/momentum_portfolio_v3_equity_{hold_days}d.csv",
        index=False
    )


summary = pd.DataFrame(
    all_summaries
)

summary.to_csv(
    "results/momentum/momentum_portfolio_v3_summary.csv",
    index=False
)

print()
print("=" * 90)
print("COMPARAISON FINALE")
print("=" * 90)

print(summary.to_string(index=False))

print()
print("Résultats sauvegardés dans :")
print("results/momentum/momentum_portfolio_v3_summary.csv")
print("=" * 90)
