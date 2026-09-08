import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")

INITIAL_CAPITAL = 10_000.0

# Contrainte expérimentale uniquement.
# Le bot final aura une gestion dynamique.
MAX_POSITIONS = 5

# 20% maximum de l'equity par position.
POSITION_SIZE = 0.20

ATR_QUANTILE = 0.80
RETURN10_QUANTILE = 0.80

HOLD_DAYS = [1, 3, 5]

START_DATE = "2022-01-01"
END_DATE = "2025-12-05"


# -------------------------------------------------------------
# WALK-FORWARD TRAIN WINDOWS
# -------------------------------------------------------------

TRAIN_WINDOWS = {
    2022: ("2018-10-16", "2021-12-31"),
    2023: ("2019-01-02", "2022-12-30"),
    2024: ("2020-01-02", "2023-12-29"),
    2025: ("2021-01-04", "2024-12-31"),
}


def get_train_thresholds(full_df, year):
    """
    Calcule les seuils uniquement avec les données disponibles
    AVANT l'année de test.
    """

    train_start, train_end = TRAIN_WINDOWS[year]

    train = full_df[
        (full_df["Date"] >= train_start)
        & (full_df["Date"] <= train_end)
    ].copy()

    train = train.dropna(
        subset=["ATR_Pct", "Return_10D"]
    )

    if train.empty:
        raise ValueError(
            f"Train vide pour {year}"
        )

    atr_threshold = train["ATR_Pct"].quantile(
        ATR_QUANTILE
    )

    return10_threshold = train["Return_10D"].quantile(
        RETURN10_QUANTILE
    )

    return (
        atr_threshold,
        return10_threshold,
        len(train)
    )


def calculate_equity(cash, positions, day):
    """
    Equity = cash + valeur de marché des positions.
    """

    positions_value = 0.0

    for position in positions:

        ticker = position["Ticker"]

        row_data = day[
            day["Ticker"] == ticker
        ]

        if row_data.empty:
            continue

        close_price = row_data.iloc[0]["Close"]

        if not np.isfinite(close_price):
            continue

        positions_value += (
            position["Shares"]
            * close_price
        )

    return cash + positions_value


def run_backtest(full_df, hold_days):

    # ---------------------------------------------------------
    # DONNÉES DE TEST
    # ---------------------------------------------------------

    test_df = full_df[
        (full_df["Date"] >= START_DATE)
        & (full_df["Date"] <= END_DATE)
    ].copy()

    test_df = test_df.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    dates = sorted(
        test_df["Date"].unique()
    )

    cash = INITIAL_CAPITAL

    positions = []

    closed_trades = []
    equity_curve = []

    threshold_cache = {}

    # ---------------------------------------------------------
    # BOUCLE JOURNALIÈRE
    # ---------------------------------------------------------

    for current_date in dates:

        day = test_df[
            test_df["Date"] == current_date
        ]

        current_year = pd.Timestamp(
            current_date
        ).year

        # -----------------------------------------------------
        # SEUILS WALK-FORWARD
        # -----------------------------------------------------

        if current_year not in threshold_cache:

            atr_threshold, return10_threshold, train_rows = (
                get_train_thresholds(
                    full_df,
                    current_year
                )
            )

            threshold_cache[current_year] = {
                "ATR": atr_threshold,
                "RETURN10": return10_threshold,
                "Train_Rows": train_rows,
            }

        thresholds = threshold_cache[current_year]

        # -----------------------------------------------------
        # 1. FERMETURE DES POSITIONS
        # -----------------------------------------------------

        positions_to_close = []

        for position in positions:

            ticker = position["Ticker"]

            row_data = day[
                day["Ticker"] == ticker
            ]

            if row_data.empty:
                continue

            row = row_data.iloc[0]

            entry_date = pd.Timestamp(
                position["Entry_Date"]
            )

            current_timestamp = pd.Timestamp(
                current_date
            )

            holding_days = (
                current_timestamp
                - entry_date
            ).days

            if holding_days >= hold_days:

                exit_price = row["Close"]

                if not np.isfinite(exit_price):
                    continue

                positions_to_close.append(
                    (
                        position,
                        exit_price,
                        "TIME"
                    )
                )

        # -----------------------------------------------------
        # 2. EXÉCUTION DES SORTIES
        # -----------------------------------------------------

        for position, exit_price, reason in positions_to_close:

            if position not in positions:
                continue

            entry_price = position["Entry_Price"]
            shares = position["Shares"]

            pnl = shares * (
                exit_price
                - entry_price
            )

            proceeds = shares * exit_price

            cash += proceeds

            holding_days = (
                pd.Timestamp(current_date)
                - pd.Timestamp(
                    position["Entry_Date"]
                )
            ).days

            closed_trades.append({
                "Ticker": position["Ticker"],
                "Entry_Date": position["Entry_Date"],
                "Exit_Date": current_date,
                "Entry_Price": entry_price,
                "Exit_Price": exit_price,
                "Shares": shares,
                "Allocation": position["Allocation"],
                "PnL": pnl,
                "Return_pct": (
                    exit_price
                    / entry_price
                    - 1
                ) * 100,
                "Holding_Days": holding_days,
                "Exit_Reason": reason,
            })

            positions.remove(position)

        # -----------------------------------------------------
        # 3. EQUITY APRÈS LES SORTIES
        # -----------------------------------------------------

        equity_before_entries = calculate_equity(
            cash,
            positions,
            day
        )

        # -----------------------------------------------------
        # 4. NOUVEAUX SIGNAUX
        # -----------------------------------------------------

        available_slots = (
            MAX_POSITIONS
            - len(positions)
        )

        if available_slots > 0:

            signals = day[
                (day["ATR_Pct"] >= thresholds["ATR"])
                &
                (day["Return_10D"] >= thresholds["RETURN10"])
            ].copy()

            # Actions déjà détenues
            held_tickers = {
                p["Ticker"]
                for p in positions
            }

            signals = signals[
                ~signals["Ticker"].isin(
                    held_tickers
                )
            ]

            # -------------------------------------------------
            # DÉPARTAGE DÉTERMINISTE
            # -------------------------------------------------

            signals = signals.sort_values(
                [
                    "ATR_Pct",
                    "Return_10D"
                ],
                ascending=False
            )

            signals = signals.head(
                available_slots
            )

            # -------------------------------------------------
            # 5. ENTRÉES
            # -------------------------------------------------

            for _, signal in signals.iterrows():

                entry_price = signal["Open"]

                if not np.isfinite(entry_price):
                    continue

                # Equity disponible au moment de l'entrée.
                current_equity = calculate_equity(
                    cash,
                    positions,
                    day
                )

                # Allocation de 20% maximum.
                allocation = (
                    current_equity
                    * POSITION_SIZE
                )

                # Impossible d'investir plus que le cash.
                allocation = min(
                    allocation,
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
                    "Shares": shares,
                    "Allocation": allocation,
                })

        # -----------------------------------------------------
        # 6. EQUITY DE FIN DE JOURNÉE
        # -----------------------------------------------------

        equity = calculate_equity(
            cash,
            positions,
            day
        )

        equity_curve.append({
            "Date": current_date,
            "Equity": equity,
            "Cash": cash,
            "Open_Positions": len(positions),
        })

    # ---------------------------------------------------------
    # 7. LIQUIDATION FINALE
    # ---------------------------------------------------------

    if positions:

        final_date = dates[-1]

        final_day = test_df[
            test_df["Date"] == final_date
        ]

        for position in positions:

            row_data = final_day[
                final_day["Ticker"]
                == position["Ticker"]
            ]

            if row_data.empty:
                continue

            exit_price = row_data.iloc[0]["Close"]

            if not np.isfinite(exit_price):
                continue

            entry_price = position["Entry_Price"]
            shares = position["Shares"]

            pnl = shares * (
                exit_price
                - entry_price
            )

            cash += shares * exit_price

            holding_days = (
                pd.Timestamp(final_date)
                - pd.Timestamp(
                    position["Entry_Date"]
                )
            ).days

            closed_trades.append({
                "Ticker": position["Ticker"],
                "Entry_Date": position["Entry_Date"],
                "Exit_Date": final_date,
                "Entry_Price": entry_price,
                "Exit_Price": exit_price,
                "Shares": shares,
                "Allocation": position["Allocation"],
                "PnL": pnl,
                "Return_pct": (
                    exit_price
                    / entry_price
                    - 1
                ) * 100,
                "Holding_Days": holding_days,
                "Exit_Reason": "FINAL",
            })

        positions = []

    trades = pd.DataFrame(
        closed_trades
    )

    equity_df = pd.DataFrame(
        equity_curve
    )

    if equity_df.empty:
        return trades, equity_df, threshold_cache

    # ---------------------------------------------------------
    # 8. DRAWDOWN
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

    return (
        trades,
        equity_df,
        threshold_cache
    )


# =============================================================
# MAIN
# =============================================================

print("=" * 90)
print("MOMENTUM V1 - REALISTIC PORTFOLIO AUDIT V4")
print("=" * 90)

# -------------------------------------------------------------
# IMPORTANT :
# on charge TOUTES les données historiques.
# -------------------------------------------------------------

full_df = pd.read_csv(
    INPUT_FILE,
    parse_dates=["Date"]
)

full_df = full_df.sort_values(
    ["Date", "Ticker"]
).reset_index(drop=True)

print(
    f"Dataset historique : "
    f"{len(full_df):,} lignes"
)

print(
    f"Actions : "
    f"{full_df['Ticker'].nunique()}"
)

print(
    f"Période historique : "
    f"{full_df['Date'].min().date()} → "
    f"{full_df['Date'].max().date()}"
)

print()
print("SEUILS WALK-FORWARD UTILISÉS")
print("-" * 90)

for year in sorted(TRAIN_WINDOWS):

    atr, ret10, rows = (
        get_train_thresholds(
            full_df,
            year
        )
    )

    print(
        f"{year} | "
        f"Train {TRAIN_WINDOWS[year][0]} → "
        f"{TRAIN_WINDOWS[year][1]} | "
        f"ATR Q80={atr:.6f} | "
        f"Return10 Q80={ret10:.6f} | "
        f"{rows:,} lignes"
    )


all_summaries = []

for hold_days in HOLD_DAYS:

    print()
    print("=" * 90)
    print(f"HOLD {hold_days} JOURS")
    print("=" * 90)

    trades, equity, thresholds = run_backtest(
        full_df,
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

    avg_positions = equity[
        "Open_Positions"
    ].mean()

    max_positions = equity[
        "Open_Positions"
    ].max()

    print(
        f"Trades        : {len(trades):,}"
    )

    print(
        f"Win rate      : {win_rate:.2f}%"
    )

    print(
        f"PnL           : "
        f"${trades['PnL'].sum():,.2f}"
    )

    print(
        f"Final equity  : "
        f"${final_equity:,.2f}"
    )

    print(
        f"Return        : "
        f"{total_return:+.2f}%"
    )

    print(
        f"Avg trade     : "
        f"{avg_trade:+.3f}%"
    )

    print(
        f"Median trade  : "
        f"{median_trade:+.3f}%"
    )

    print(
        f"Profit factor : "
        f"{profit_factor:.2f}"
    )

    print(
        f"Max drawdown  : "
        f"{max_dd:+.2f}%"
    )

    print(
        f"Positions moy.: "
        f"{avg_positions:.2f}"
    )

    print(
        f"Positions max.: "
        f"{max_positions}"
    )

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

    # ---------------------------------------------------------
    # CONTRÔLE DE COHÉRENCE
    # ---------------------------------------------------------

    total_pnl = trades["PnL"].sum()

    expected_final = (
        INITIAL_CAPITAL
        + total_pnl
    )

    difference = (
        final_equity
        - expected_final
    )

    print()
    print("Contrôle comptable :")

    print(
        f"  Capital initial + PnL = "
        f"${expected_final:,.2f}"
    )

    print(
        f"  Equity finale         = "
        f"${final_equity:,.2f}"
    )

    print(
        f"  Différence            = "
        f"${difference:+,.6f}"
    )

    all_summaries.append({
        "Hold_Days": hold_days,
        "Trades": len(trades),
        "Win_Rate_pct": win_rate,
        "PnL": total_pnl,
        "Final_Equity": final_equity,
        "Return_pct": total_return,
        "Avg_Trade_pct": avg_trade,
        "Median_Trade_pct": median_trade,
        "Profit_Factor": profit_factor,
        "Max_Drawdown_pct": max_dd,
        "Avg_Open_Positions": avg_positions,
        "Max_Open_Positions": max_positions,
        "Accounting_Difference": difference,
    })

    trades.to_csv(
        f"results/momentum/momentum_portfolio_v4_trades_{hold_days}d.csv",
        index=False
    )

    equity.to_csv(
        f"results/momentum/momentum_portfolio_v4_equity_{hold_days}d.csv",
        index=False
    )


summary = pd.DataFrame(
    all_summaries
)

summary.to_csv(
    "results/momentum/momentum_portfolio_v4_summary.csv",
    index=False
)

print()
print("=" * 90)
print("COMPARAISON FINALE")
print("=" * 90)

print(
    summary.to_string(
        index=False
    )
)

print()
print(
    "Résultats sauvegardés dans :"
)

print(
    "results/momentum/momentum_portfolio_v4_summary.csv"
)

print("=" * 90)
