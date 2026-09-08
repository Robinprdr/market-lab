import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("results/momentum/momentum_v1_research.csv")

INITIAL_CAPITAL = 10_000.0

MAX_POSITIONS = 5
POSITION_SIZE = 0.20

ATR_QUANTILE = 0.80
RETURN10_QUANTILE = 0.80

HOLD_DAYS = [1, 3, 5]

START_DATE = "2022-01-01"
END_DATE = "2025-12-05"

TRAIN_WINDOWS = {
    2022: ("2018-10-16", "2021-12-31"),
    2023: ("2019-01-02", "2022-12-30"),
    2024: ("2020-01-02", "2023-12-29"),
    2025: ("2021-01-04", "2024-12-31"),
}

# ============================================================
# COUTS
# ============================================================
# Scénario réaliste :
# 0.05% de frais à l'achat
# 0.05% de frais à la vente
# 0.05% de slippage à l'achat
# 0.05% de slippage à la vente
#
# Total approximatif aller-retour = 0.20%
# ============================================================

FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0005


def get_train_thresholds(full_df, year):
    train_start, train_end = TRAIN_WINDOWS[year]

    train = full_df[
        (full_df["Date"] >= train_start)
        & (full_df["Date"] <= train_end)
    ].copy()

    train = train.dropna(subset=["ATR_Pct", "Return_10D"])

    if train.empty:
        raise ValueError(f"Train vide pour {year}")

    atr_threshold = train["ATR_Pct"].quantile(ATR_QUANTILE)
    return10_threshold = train["Return_10D"].quantile(RETURN10_QUANTILE)

    return atr_threshold, return10_threshold, len(train)


def calculate_equity(cash, positions, day):
    positions_value = 0.0

    for position in positions:
        ticker = position["Ticker"]

        row_data = day[day["Ticker"] == ticker]

        if row_data.empty:
            continue

        close_price = row_data.iloc[0]["Close"]

        if not np.isfinite(close_price):
            continue

        # Valeur de marché actuelle
        positions_value += position["Shares"] * close_price

    return cash + positions_value


def run_backtest(full_df, hold_days):

    test_df = full_df[
        (full_df["Date"] >= START_DATE)
        & (full_df["Date"] <= END_DATE)
    ].copy()

    test_df = test_df.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    dates = sorted(test_df["Date"].unique())

    cash = INITIAL_CAPITAL
    positions = []
    closed_trades = []
    equity_curve = []

    threshold_cache = {}

    for current_date in dates:

        day = test_df[
            test_df["Date"] == current_date
        ]

        current_year = pd.Timestamp(current_date).year

        # ----------------------------------------------------
        # WALK-FORWARD THRESHOLDS
        # ----------------------------------------------------

        if current_year not in threshold_cache:

            atr_threshold, return10_threshold, train_rows = \
                get_train_thresholds(
                    full_df,
                    current_year
                )

            threshold_cache[current_year] = {
                "ATR": atr_threshold,
                "RETURN10": return10_threshold,
                "Train_Rows": train_rows,
            }

        thresholds = threshold_cache[current_year]

        # ----------------------------------------------------
        # FERMETURE DES POSITIONS
        # ----------------------------------------------------

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
                current_timestamp - entry_date
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

        # ----------------------------------------------------
        # EXECUTION DES SORTIES
        # ----------------------------------------------------

        for position, raw_exit_price, reason in positions_to_close:

            if position not in positions:
                continue

            entry_price = position["Entry_Price"]
            shares = position["Shares"]

            # Slippage vendeur :
            # on vend légèrement moins cher
            exit_price = raw_exit_price * (
                1 - SLIPPAGE_RATE
            )

            gross_proceeds = (
                shares * exit_price
            )

            sell_fee = (
                gross_proceeds * FEE_RATE
            )

            net_proceeds = (
                gross_proceeds - sell_fee
            )

            cash += net_proceeds

            pnl = (
                net_proceeds
                - position["Total_Cost"]
            )

            holding_days = (
                pd.Timestamp(current_date)
                - pd.Timestamp(position["Entry_Date"])
            ).days

            closed_trades.append({

                "Ticker":
                    position["Ticker"],

                "Entry_Date":
                    position["Entry_Date"],

                "Exit_Date":
                    current_date,

                "Raw_Entry_Price":
                    position["Raw_Entry_Price"],

                "Entry_Price":
                    entry_price,

                "Raw_Exit_Price":
                    raw_exit_price,

                "Exit_Price":
                    exit_price,

                "Shares":
                    shares,

                "Allocation":
                    position["Allocation"],

                "Buy_Fee":
                    position["Buy_Fee"],

                "Sell_Fee":
                    sell_fee,

                "Slippage_Cost":
                    position["Slippage_Cost"]
                    + shares * (
                        raw_exit_price
                        - exit_price
                    ),

                "Total_Cost":
                    position["Total_Cost"]
                    + sell_fee,

                "PnL":
                    pnl,

                "Return_pct":
                    (
                        net_proceeds
                        / position["Total_Cost"]
                        - 1
                    ) * 100,

                "Holding_Days":
                    holding_days,

                "Exit_Reason":
                    reason,
            })

            positions.remove(position)

        # ----------------------------------------------------
        # NOUVELLES ENTREES
        # ----------------------------------------------------

        available_slots = (
            MAX_POSITIONS
            - len(positions)
        )

        if available_slots > 0:

            signals = day[
                (day["ATR_Pct"] >= thresholds["ATR"])
                &
                (
                    day["Return_10D"]
                    >= thresholds["RETURN10"]
                )
            ].copy()

            held_tickers = {
                p["Ticker"]
                for p in positions
            }

            signals = signals[
                ~signals["Ticker"].isin(
                    held_tickers
                )
            ]

            # Classement :
            # 1. ATR le plus élevé
            # 2. Return 10D le plus élevé
            signals = signals.sort_values(
                ["ATR_Pct", "Return_10D"],
                ascending=False
            )

            signals = signals.head(
                available_slots
            )

            # ------------------------------------------------
            # EXECUTION DES ACHATS
            # ------------------------------------------------

            for _, signal in signals.iterrows():

                raw_entry_price = signal["Open"]

                if not np.isfinite(
                    raw_entry_price
                ):
                    continue

                current_equity = calculate_equity(
                    cash,
                    positions,
                    day
                )

                allocation = (
                    current_equity
                    * POSITION_SIZE
                )

                allocation = min(
                    allocation,
                    cash
                )

                if allocation <= 0:
                    continue

                # Slippage acheteur :
                # on achète légèrement plus cher
                entry_price = (
                    raw_entry_price
                    * (1 + SLIPPAGE_RATE)
                )

                # Allocation représente le cash
                # réellement déboursé, frais inclus.
                buy_fee = (
                    allocation
                    * FEE_RATE
                )

                total_cost = allocation

                # Montant réellement disponible
                # pour acheter les actions
                net_stock_value = (
                    allocation
                    - buy_fee
                )

                shares = (
                    net_stock_value
                    / entry_price
                )

                if shares <= 0:
                    continue

                slippage_cost = (
                    shares
                    * (
                        entry_price
                        - raw_entry_price
                    )
                )

                cash -= total_cost

                positions.append({

                    "Ticker":
                        signal["Ticker"],

                    "Entry_Date":
                        current_date,

                    "Raw_Entry_Price":
                        raw_entry_price,

                    "Entry_Price":
                        entry_price,

                    "Shares":
                        shares,

                    "Allocation":
                        allocation,

                    "Buy_Fee":
                        buy_fee,

                    "Slippage_Cost":
                        slippage_cost,

                    "Total_Cost":
                        total_cost,
                })

        # ----------------------------------------------------
        # EQUITY JOURNALIERE
        # ----------------------------------------------------

        equity = calculate_equity(
            cash,
            positions,
            day
        )

        equity_curve.append({

            "Date":
                current_date,

            "Equity":
                equity,

            "Cash":
                cash,

            "Open_Positions":
                len(positions),
        })

    # ========================================================
    # LIQUIDATION FINALE
    # ========================================================

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

            raw_exit_price = row_data.iloc[0]["Close"]

            if not np.isfinite(
                raw_exit_price
            ):
                continue

            exit_price = (
                raw_exit_price
                * (1 - SLIPPAGE_RATE)
            )

            shares = position["Shares"]

            gross_proceeds = (
                shares
                * exit_price
            )

            sell_fee = (
                gross_proceeds
                * FEE_RATE
            )

            net_proceeds = (
                gross_proceeds
                - sell_fee
            )

            cash += net_proceeds

            pnl = (
                net_proceeds
                - position["Total_Cost"]
            )

            holding_days = (
                pd.Timestamp(final_date)
                - pd.Timestamp(position["Entry_Date"])
            ).days

            closed_trades.append({

                "Ticker":
                    position["Ticker"],

                "Entry_Date":
                    position["Entry_Date"],

                "Exit_Date":
                    final_date,

                "Raw_Entry_Price":
                    position["Raw_Entry_Price"],

                "Entry_Price":
                    position["Entry_Price"],

                "Raw_Exit_Price":
                    raw_exit_price,

                "Exit_Price":
                    exit_price,

                "Shares":
                    shares,

                "Allocation":
                    position["Allocation"],

                "Buy_Fee":
                    position["Buy_Fee"],

                "Sell_Fee":
                    sell_fee,

                "Slippage_Cost":
                    position["Slippage_Cost"]
                    + shares * (
                        raw_exit_price
                        - exit_price
                    ),

                "Total_Cost":
                    position["Total_Cost"]
                    + sell_fee,

                "PnL":
                    pnl,

                "Return_pct":
                    (
                        net_proceeds
                        / position["Total_Cost"]
                        - 1
                    ) * 100,

                "Holding_Days":
                    holding_days,

                "Exit_Reason":
                    "FINAL",
            })

        positions = []

    # ========================================================
    # EQUITY CURVE
    # ========================================================

    trades = pd.DataFrame(
        closed_trades
    )

    equity_df = pd.DataFrame(
        equity_curve
    )

    if equity_df.empty:
        return (
            trades,
            equity_df,
            threshold_cache
        )

    equity_df["Peak"] = (
        equity_df["Equity"].cummax()
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


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

print("=" * 90)
print("MOMENTUM V1 - PORTFOLIO V5")
print("FRAIS + SLIPPAGE")
print("=" * 90)

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
    f"{full_df['Date'].min().date()} "
    f"→ "
    f"{full_df['Date'].max().date()}"
)

print()
print("PARAMETRES DE COUT")
print("-" * 90)

print(
    f"Frais achat     : "
    f"{FEE_RATE * 100:.3f}%"
)

print(
    f"Frais vente     : "
    f"{FEE_RATE * 100:.3f}%"
)

print(
    f"Slippage achat : "
    f"{SLIPPAGE_RATE * 100:.3f}%"
)

print(
    f"Slippage vente : "
    f"{SLIPPAGE_RATE * 100:.3f}%"
)

print(
    f"Cout aller-retour approximatif : "
    f"{(2 * FEE_RATE + 2 * SLIPPAGE_RATE) * 100:.2f}%"
)

print()
print("SEUILS WALK-FORWARD")
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
        f"Train "
        f"{TRAIN_WINDOWS[year][0]} "
        f"→ "
        f"{TRAIN_WINDOWS[year][1]} | "
        f"ATR Q80={atr:.6f} | "
        f"Return10 Q80={ret10:.6f} | "
        f"{rows:,} lignes"
    )


all_summaries = []

for hold_days in HOLD_DAYS:

    print()
    print("=" * 90)
    print(
        f"HOLD {hold_days} JOURS"
    )
    print("=" * 90)

    trades, equity, thresholds = (
        run_backtest(
            full_df,
            hold_days
        )
    )

    if trades.empty:

        print("Aucun trade.")
        continue

    final_equity = (
        equity.iloc[-1]["Equity"]
    )

    total_return = (
        final_equity
        / INITIAL_CAPITAL
        - 1
    ) * 100

    win_rate = (
        trades["PnL"] > 0
    ).mean() * 100

    avg_trade = (
        trades["Return_pct"].mean()
    )

    median_trade = (
        trades["Return_pct"].median()
    )

    gross_profit = (
        trades.loc[
            trades["PnL"] > 0,
            "PnL"
        ].sum()
    )

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

    max_dd = (
        equity["Drawdown_pct"].min()
    )

    avg_positions = (
        equity["Open_Positions"].mean()
    )

    max_positions = (
        equity["Open_Positions"].max()
    )

    total_fees = (
        trades["Buy_Fee"].sum()
        + trades["Sell_Fee"].sum()
    )

    total_slippage = (
        trades["Slippage_Cost"].sum()
    )

    print(
        f"Trades        : "
        f"{len(trades):,}"
    )

    print(
        f"Win rate      : "
        f"{win_rate:.2f}%"
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

    print(
        f"Frais totaux  : "
        f"${total_fees:,.2f}"
    )

    print(
        f"Slippage total: "
        f"${total_slippage:,.2f}"
    )

    print()
    print("Trades par année :")

    trades["Exit_Year"] = (
        pd.to_datetime(
            trades["Exit_Date"]
        ).dt.year
    )

    yearly = (
        trades.groupby("Exit_Year")["PnL"]
        .sum()
    )

    for year, pnl in yearly.items():

        print(
            f"  {year} : "
            f"${pnl:+,.2f}"
        )

    # --------------------------------------------------------
    # CONTROLE COMPTABLE
    # --------------------------------------------------------

    total_pnl = (
        trades["PnL"].sum()
    )

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
        f"${difference:+.6f}"
    )

    all_summaries.append({

        "Hold_Days":
            hold_days,

        "Trades":
            len(trades),

        "Win_Rate_pct":
            win_rate,

        "PnL":
            total_pnl,

        "Final_Equity":
            final_equity,

        "Return_pct":
            total_return,

        "Avg_Trade_pct":
            avg_trade,

        "Median_Trade_pct":
            median_trade,

        "Profit_Factor":
            profit_factor,

        "Max_Drawdown_pct":
            max_dd,

        "Avg_Open_Positions":
            avg_positions,

        "Max_Open_Positions":
            max_positions,

        "Total_Fees":
            total_fees,

        "Total_Slippage":
            total_slippage,

        "Accounting_Difference":
            difference,
    })

    trades.to_csv(
        f"results/momentum/"
        f"momentum_portfolio_v5_costs_trades_"
        f"{hold_days}d.csv",
        index=False
    )

    equity.to_csv(
        f"results/momentum/"
        f"momentum_portfolio_v5_costs_equity_"
        f"{hold_days}d.csv",
        index=False
    )


summary = pd.DataFrame(
    all_summaries
)

summary.to_csv(
    "results/momentum/"
    "momentum_portfolio_v5_costs_summary.csv",
    index=False
)

print()
print("=" * 90)
print("COMPARAISON FINALE V5")
print("=" * 90)

print(
    summary.to_string(
        index=False
    )
)

print()
print("Résultats sauvegardés dans :")
print(
    "results/momentum/"
    "momentum_portfolio_v5_costs_summary.csv"
)

print("=" * 90)
