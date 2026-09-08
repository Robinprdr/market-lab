import os
import numpy as np
import pandas as pd

# ============================================================
# MOMENTUM V1 - SIGNAL ONLY BACKTEST V2
# Portefeuille continu 2022 -> 2025
# ============================================================

DATA_FILE = "results/momentum/momentum_v1_research.csv"

INITIAL_CAPITAL = 10_000.0
POSITION_PCT = 0.20
MAX_POSITIONS = 5

HOLD_PERIODS = [1, 3, 5]

OUTPUT_DIR = "results/momentum"


# ============================================================
# UTILITAIRES
# ============================================================

def profit_factor(returns):
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()

    if losses == 0:
        return np.inf

    return gains / losses


def max_drawdown(equity):
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return drawdown.min()


def prepare_data():
    df = pd.read_csv(DATA_FILE)

    df["Date"] = pd.to_datetime(df["Date"])

    required = [
        "Date",
        "Ticker",
        "Open",
        "Close",
        "ATR_Pct",
        "Return_10D",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"Colonnes manquantes : {missing}")

    df = df.sort_values(["Ticker", "Date"]).copy()

    # On ne travaille que sur la période où les seuils
    # walk-forward sont déjà définis.
    # IMPORTANT :
    # On conserve toute l'historique pour pouvoir calculer
    # les seuils Q80 du train, notamment pour 2022.
    # La période 2022-2025 sera filtrée uniquement au moment
    # du backtest.

    return df


# ============================================================
# SEUILS WALK-FORWARD
# ============================================================

def get_train_data(full_df, test_year):
    """
    Les seuils sont calculés uniquement avec les données
    disponibles AVANT l'année test.
    """

    if test_year == 2022:
        train_start = "2018-10-16"
        train_end = "2021-12-31"

    elif test_year == 2023:
        train_start = "2019-01-02"
        train_end = "2022-12-30"

    elif test_year == 2024:
        train_start = "2020-01-02"
        train_end = "2023-12-29"

    elif test_year == 2025:
        train_start = "2021-01-04"
        train_end = "2024-12-31"

    else:
        raise ValueError(f"Année inconnue : {test_year}")

    train = full_df[
        (full_df["Date"] >= train_start)
        & (full_df["Date"] <= train_end)
    ].copy()

    return train


def get_thresholds(full_df, test_year):
    train = get_train_data(full_df, test_year)

    atr_threshold = train["ATR_Pct"].quantile(0.80)
    return10_threshold = train["Return_10D"].quantile(0.80)

    return atr_threshold, return10_threshold


# ============================================================
# TEST D'UNE ANNÉE
# ============================================================

def prepare_year_data(full_df, year):
    test = full_df[
        full_df["Date"].dt.year == year
    ].copy()

    test = test.sort_values(["Date", "Ticker"]).copy()

    atr_q80, return10_q80 = get_thresholds(full_df, year)

    test["Signal"] = (
        (test["ATR_Pct"] >= atr_q80)
        & (test["Return_10D"] >= return10_q80)
    )

    return test, atr_q80, return10_q80


# ============================================================
# PORTFOLIO BACKTEST
# ============================================================

def run_backtest(full_df, hold_period):
    cash = INITIAL_CAPITAL

    positions = {}
    pending_entries = {}

    trades = []
    equity_records = []

    all_years = [2022, 2023, 2024, 2025]

    for year in all_years:

        year_df, atr_q80, return10_q80 = prepare_year_data(
            full_df,
            year
        )

        dates = sorted(year_df["Date"].unique())

        print()
        print(f"Window {year} | Hold {hold_period} séance(s)")
        print(f"ATR Q80      : {atr_q80:.6f}")
        print(f"Return10 Q80 : {return10_q80:.6f}")

        # ----------------------------------------------------
        # Création des signaux -> entrée au prochain Open
        # ----------------------------------------------------

        for date in dates:

            day = year_df[
                year_df["Date"] == date
            ].copy()

            # ------------------------------------------------
            # 1. ENTRÉES À L'OPEN
            # ------------------------------------------------

            entries_today = pending_entries.pop(
                pd.Timestamp(date),
                []
            )

            # Maximum 5 positions simultanées.
            # Les signaux sont triés par ticker afin d'avoir
            # une règle déterministe et non subjective.
            entries_today = sorted(
                entries_today,
                key=lambda x: x["Ticker"]
            )

            current_positions = len(positions)

            available_slots = MAX_POSITIONS - current_positions

            if available_slots > 0:

                entries_today = entries_today[:available_slots]

                # Equity disponible au début de la séance.
                previous_values = 0.0

                for pos in positions.values():
                    previous_values += (
                        pos["Shares"] * pos["Previous_Close"]
                    )

                equity_at_open = cash + previous_values

                for signal in entries_today:

                    ticker = signal["Ticker"]

                    if ticker in positions:
                        continue

                    open_price = signal["Open"]

                    if not np.isfinite(open_price) or open_price <= 0:
                        continue

                    position_value = equity_at_open * POSITION_PCT

                    # On ne peut jamais investir plus que le cash.
                    position_value = min(
                        position_value,
                        cash
                    )

                    if position_value <= 0:
                        continue

                    shares = position_value / open_price

                    cash -= position_value

                    positions[ticker] = {
                        "Ticker": ticker,
                        "Entry_Date": pd.Timestamp(date),
                        "Entry_Price": open_price,
                        "Shares": shares,
                        "Position_Value": position_value,
                        "Hold_Sessions": 1,
                        "Previous_Close": open_price,
                        "ATR_Pct": signal["ATR_Pct"],
                        "Return_10D": signal["Return_10D"],
                    }

                    current_positions += 1

                    if current_positions >= MAX_POSITIONS:
                        break

            # ------------------------------------------------
            # 2. COURS DE CLÔTURE
            # ------------------------------------------------

            close_prices = {}

            for _, row in day.iterrows():
                close_prices[row["Ticker"]] = row["Close"]

            # ------------------------------------------------
            # 3. MISE À JOUR DES POSITIONS
            # ------------------------------------------------

            exits_today = []

            for ticker, pos in list(positions.items()):

                if ticker not in close_prices:
                    continue

                close_price = close_prices[ticker]

                if not np.isfinite(close_price):
                    continue

                pos["Previous_Close"] = close_price

                # Une position entrée aujourd'hui compte
                # comme 1 séance de détention.
                #
                # Si Hold=1 -> sortie aujourd'hui à la clôture.
                # Si Hold=3 -> sortie après 3 clôtures.
                if pos["Hold_Sessions"] >= hold_period:
                    exits_today.append(ticker)
                else:
                    pos["Hold_Sessions"] += 1

            # ------------------------------------------------
            # 4. SORTIES À LA CLÔTURE
            # ------------------------------------------------

            for ticker in exits_today:

                pos = positions.pop(ticker)

                exit_price = close_prices[ticker]

                pnl = (
                    exit_price - pos["Entry_Price"]
                ) * pos["Shares"]

                trade_return = (
                    exit_price / pos["Entry_Price"]
                ) - 1.0

                cash += exit_price * pos["Shares"]

                trades.append({
                    "Ticker": ticker,
                    "Entry_Date": pos["Entry_Date"],
                    "Exit_Date": pd.Timestamp(date),
                    "Entry_Price": pos["Entry_Price"],
                    "Exit_Price": exit_price,
                    "Shares": pos["Shares"],
                    "Position_Value": pos["Position_Value"],
                    "PnL": pnl,
                    "Return": trade_return,
                    "Hold_Sessions": hold_period,
                    "ATR_Pct": pos["ATR_Pct"],
                    "Return_10D": pos["Return_10D"],
                })

            # ------------------------------------------------
            # 5. VALEUR DU PORTEFEUILLE EN FIN DE JOURNÉE
            # ------------------------------------------------

            position_market_value = 0.0

            for pos in positions.values():

                ticker = pos["Ticker"]

                if ticker in close_prices:
                    position_market_value += (
                        pos["Shares"]
                        * close_prices[ticker]
                    )

            equity = cash + position_market_value

            equity_records.append({
                "Date": pd.Timestamp(date),
                "Equity": equity,
                "Cash": cash,
                "Open_Positions": len(positions),
                "Hold_Period": hold_period,
            })

            # ------------------------------------------------
            # 6. SIGNALS DU JOUR -> ENTRÉES DU PROCHAIN JOUR
            # ------------------------------------------------

            for _, row in day[day["Signal"]].iterrows():

                ticker = row["Ticker"]

                # Ne pas programmer une entrée si déjà en position.
                if ticker in positions:
                    continue

                # Trouver la prochaine date de marché
                # pour CE ticker.
                ticker_data = full_df[
                    full_df["Ticker"] == ticker
                ].sort_values("Date")

                future_dates = ticker_data[
                    ticker_data["Date"] > pd.Timestamp(date)
                ]["Date"]

                if future_dates.empty:
                    continue

                next_date = future_dates.iloc[0]

                # On ne trade que dans la période de test.
                if next_date.year not in all_years:
                    continue

                next_rows = ticker_data[
                    ticker_data["Date"] == next_date
                ]

                if next_rows.empty:
                    continue

                next_row = next_rows.iloc[0]

                if not np.isfinite(next_row["Open"]):
                    continue

                pending_entries.setdefault(
                    pd.Timestamp(next_date),
                    []
                ).append({
                    "Ticker": ticker,
                    "Open": next_row["Open"],
                    "ATR_Pct": row["ATR_Pct"],
                    "Return_10D": row["Return_10D"],
                })

    # ========================================================
    # FIN DU BACKTEST
    # ========================================================

    # Fermer les éventuelles positions restantes au dernier prix.
    if positions:

        last_date = max(
            pd.Timestamp(x["Date"])
            for x in equity_records
        )

        last_day = full_df[
            full_df["Date"] == last_date
        ]

        last_close = dict(
            zip(last_day["Ticker"], last_day["Close"])
        )

        for ticker, pos in list(positions.items()):

            if ticker not in last_close:
                continue

            exit_price = last_close[ticker]

            pnl = (
                exit_price - pos["Entry_Price"]
            ) * pos["Shares"]

            trade_return = (
                exit_price / pos["Entry_Price"]
            ) - 1.0

            cash += exit_price * pos["Shares"]

            trades.append({
                "Ticker": ticker,
                "Entry_Date": pos["Entry_Date"],
                "Exit_Date": last_date,
                "Entry_Price": pos["Entry_Price"],
                "Exit_Price": exit_price,
                "Shares": pos["Shares"],
                "Position_Value": pos["Position_Value"],
                "PnL": pnl,
                "Return": trade_return,
                "Hold_Sessions": pos["Hold_Sessions"],
                "ATR_Pct": pos["ATR_Pct"],
                "Return_10D": pos["Return_10D"],
            })

            positions.pop(ticker)

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_records)

    if equity_df.empty:
        raise ValueError("Aucune donnée d'equity générée.")

    # ========================================================
    # STATISTIQUES
    # ========================================================

    final_equity = equity_df["Equity"].iloc[-1]

    total_pnl = final_equity - INITIAL_CAPITAL

    portfolio_return = (
        final_equity / INITIAL_CAPITAL
    ) - 1.0

    if not trades_df.empty:

        returns = trades_df["Return"]

        win_rate = (
            (returns > 0).mean()
        )

        avg_return = returns.mean()
        median_return = returns.median()

        pf = profit_factor(returns)

    else:
        win_rate = 0
        avg_return = 0
        median_return = 0
        pf = 0

    dd = max_drawdown(
        equity_df["Equity"]
    )

    return {
        "Hold_Period": hold_period,
        "Trades": len(trades_df),
        "Wins": int((trades_df["Return"] > 0).sum())
            if not trades_df.empty else 0,
        "Losses": int((trades_df["Return"] < 0).sum())
            if not trades_df.empty else 0,
        "Win_Rate": win_rate,
        "PnL": total_pnl,
        "Final_Equity": final_equity,
        "Portfolio_Return": portfolio_return,
        "Avg_Return": avg_return,
        "Median_Return": median_return,
        "Profit_Factor": pf,
        "Max_Drawdown": dd,
    }, trades_df, equity_df


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("MOMENTUM V1 - SIGNAL ONLY BACKTEST V2")
    print("PORTEFEUILLE CONTINU")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = prepare_data()

    print(f"Dataset : {len(df):,} lignes")
    print(f"Actions : {df['Ticker'].nunique()}")
    print(
        f"Période : "
        f"{df['Date'].min().date()} -> "
        f"{df['Date'].max().date()}"
    )

    all_summaries = []
    all_trades = []
    all_equity = []

    for hold in HOLD_PERIODS:

        summary, trades, equity = run_backtest(
            df,
            hold
        )

        all_summaries.append(summary)

        if not trades.empty:
            trades["Hold_Period"] = hold
            all_trades.append(trades)

        equity["Hold_Period"] = hold
        all_equity.append(equity)

    summary_df = pd.DataFrame(all_summaries)

    trades_df = (
        pd.concat(all_trades, ignore_index=True)
        if all_trades
        else pd.DataFrame()
    )

    equity_df = pd.concat(
        all_equity,
        ignore_index=True
    )

    # ========================================================
    # AFFICHAGE
    # ========================================================

    print()
    print("=" * 70)
    print("RÉSULTATS")
    print("=" * 70)

    for _, row in summary_df.iterrows():

        print()
        print(
            f"HOLD {int(row['Hold_Period'])} SÉANCE(S)"
        )
        print("-" * 50)

        print(
            f"Trades             : "
            f"{int(row['Trades']):,}"
        )

        print(
            f"Win rate           : "
            f"{row['Win_Rate']:.2%}"
        )

        print(
            f"PnL                : "
            f"${row['PnL']:,.2f}"
        )

        print(
            f"Capital final      : "
            f"${row['Final_Equity']:,.2f}"
        )

        print(
            f"Return portefeuille: "
            f"{row['Portfolio_Return']:.2%}"
        )

        print(
            f"Trade moyen        : "
            f"{row['Avg_Return']:.3%}"
        )

        print(
            f"Trade médian       : "
            f"{row['Median_Return']:.3%}"
        )

        print(
            f"Profit Factor      : "
            f"{row['Profit_Factor']:.2f}"
        )

        print(
            f"Max DD portefeuille: "
            f"{row['Max_Drawdown']:.2%}"
        )

    # ========================================================
    # PERFORMANCE PAR ANNÉE
    # ========================================================

    print()
    print("=" * 70)
    print("PERFORMANCE PAR ANNÉE")
    print("=" * 70)

    if not trades_df.empty:

        trades_df["Year"] = pd.to_datetime(
            trades_df["Exit_Date"]
        ).dt.year

        for hold in HOLD_PERIODS:

            temp = trades_df[
                trades_df["Hold_Period"] == hold
            ].copy()

            annual = temp.groupby("Year").agg(
                Trades=("Return", "count"),
                PnL=("PnL", "sum"),
                Avg_Return=("Return", "mean"),
                Win_Rate=(
                    "Return",
                    lambda x: (x > 0).mean()
                ),
            )

            print()
            print(f"--- HOLD {hold} ---")
            print(annual)

    # ========================================================
    # SAUVEGARDE
    # ========================================================

    summary_path = (
        f"{OUTPUT_DIR}/"
        "momentum_signal_v2_summary.csv"
    )

    trades_path = (
        f"{OUTPUT_DIR}/"
        "momentum_signal_v2_trades.csv"
    )

    equity_path = (
        f"{OUTPUT_DIR}/"
        "momentum_signal_v2_equity.csv"
    )

    summary_df.to_csv(
        summary_path,
        index=False
    )

    trades_df.to_csv(
        trades_path,
        index=False
    )

    equity_df.to_csv(
        equity_path,
        index=False
    )

    print()
    print("=" * 70)
    print("FICHIERS CRÉÉS")
    print("=" * 70)

    print(summary_path)
    print(trades_path)
    print(equity_path)

    print()
    print("FIN")


if __name__ == "__main__":
    main()
