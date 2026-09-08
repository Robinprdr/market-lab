import pandas as pd
import numpy as np
from pathlib import Path

DATA_PATH = Path("results/momentum/momentum_v1_research.csv")

INITIAL_CAPITAL = 10_000.0
START_DATE = "2022-01-01"
END_DATE = "2025-12-31"

HOLD_DAYS = 3
MAX_POSITIONS = 5

BUY_FEE = 0.0005
SELL_FEE = 0.0005
BUY_SLIPPAGE = 0.0005
SELL_SLIPPAGE = 0.0005

SIZINGS = [0.10, 0.15, 0.20, 0.25]


def q80(series):
    return series.dropna().quantile(0.80)


def max_drawdown(equity):
    if len(equity) == 0:
        return 0.0

    equity = pd.Series(equity, dtype=float)
    peak = equity.cummax()
    dd = equity / peak - 1.0

    return float(dd.min())


def prepare_data():
    df = pd.read_csv(
        DATA_PATH,
        parse_dates=["Date"]
    )

    df = df.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    return df


def build_v5_1_thresholds(df):
    """
    Reproduit le principe walk-forward V5.1 :
    chaque année utilise les 3 années précédentes
    comme période d'entraînement.

    2022 -> 2019-2021
    2023 -> 2020-2022
    2024 -> 2021-2023
    2025 -> 2022-2024
    """

    thresholds = {}

    for year in range(2022, 2026):

        train_start = pd.Timestamp(
            f"{year - 3}-01-01"
        )

        train_end = pd.Timestamp(
            f"{year - 1}-12-31"
        )

        test_start = pd.Timestamp(
            f"{year}-01-01"
        )

        test_end = pd.Timestamp(
            f"{year}-12-31"
        )

        train = df[
            (df["Date"] >= train_start) &
            (df["Date"] <= train_end)
        ].copy()

        atr_threshold = q80(
            train["ATR_Pct"]
        )

        ret10_threshold = q80(
            train["Return_10D"]
        )

        thresholds[year] = {
            "atr": atr_threshold,
            "ret10": ret10_threshold,
        }

        test_rows = df[
            (df["Date"] >= test_start) &
            (df["Date"] <= test_end)
        ]

        print(
            f"{year}: "
            f"TRAIN {train_start.date()} -> {train_end.date()} | "
            f"ATR Q80={atr_threshold:.6f}, "
            f"Return10 Q80={ret10_threshold:.6f} | "
            f"test rows={len(test_rows):,}"
        )

    return thresholds


def run_backtest(df, thresholds, allocation):

    df = df[
        (df["Date"] >= pd.Timestamp(START_DATE)) &
        (df["Date"] <= pd.Timestamp(END_DATE))
    ].copy()

    df["Signal"] = False

    for year, threshold in thresholds.items():

        mask = df["Date"].dt.year == year

        df.loc[mask, "Signal"] = (
            (df.loc[mask, "ATR_Pct"] >= threshold["atr"]) &
            (df.loc[mask, "Return_10D"] >= threshold["ret10"])
        )

    df = df.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    dates = sorted(
        df["Date"].dropna().unique()
    )

    date_to_index = {
        pd.Timestamp(date): i
        for i, date in enumerate(dates)
    }

    cash = INITIAL_CAPITAL

    positions = []
    trades = []
    equity_curve = []

    cash_blocked = 0
    max_positions_seen = 0

    for raw_date in dates:

        current_date = pd.Timestamp(raw_date)

        today = df[
            df["Date"] == current_date
        ]

        prices = dict(
            zip(
                today["Ticker"],
                today["Close"]
            )
        )

        # --------------------------------------------------
        # 1. EQUITY AVANT ACTION
        # --------------------------------------------------

        equity = cash

        for pos in positions:

            price = prices.get(
                pos["Ticker"]
            )

            if price is not None and not pd.isna(price):

                equity += (
                    pos["shares"] *
                    float(price)
                )

        equity_curve.append(
            {
                "Date": current_date,
                "Equity": equity
            }
        )

        # --------------------------------------------------
        # 2. SORTIES
        # --------------------------------------------------

        remaining = []

        current_index = date_to_index[
            current_date
        ]

        for pos in positions:

            holding_days = (
                current_index -
                pos["entry_index"]
            )

            if holding_days < HOLD_DAYS:

                remaining.append(pos)
                continue

            row = today[
                today["Ticker"] ==
                pos["Ticker"]
            ]

            if len(row) == 0:

                remaining.append(pos)
                continue

            exit_raw = float(
                row.iloc[0]["Open"]
            )

            if pd.isna(exit_raw):

                remaining.append(pos)
                continue

            exit_price = (
                exit_raw *
                (1.0 - SELL_SLIPPAGE)
            )

            gross_value = (
                pos["shares"] *
                exit_price
            )

            sell_fee = (
                gross_value *
                SELL_FEE
            )

            proceeds = (
                gross_value -
                sell_fee
            )

            cash += proceeds

            pnl = (
                proceeds -
                pos["cash_deployed"]
            )

            trades.append(
                {
                    "Ticker": pos["Ticker"],
                    "Entry_Date": pos["entry_date"],
                    "Exit_Date": current_date,
                    "Entry_Price": pos["entry_price"],
                    "Exit_Price": exit_price,
                    "Shares": pos["shares"],
                    "Cash_Deployed": pos["cash_deployed"],
                    "PnL": pnl,
                    "Return": (
                        pnl /
                        pos["cash_deployed"]
                    )
                }
            )

        positions = remaining

        # --------------------------------------------------
        # 3. NOUVEAUX SIGNAUX
        # --------------------------------------------------

        available_slots = (
            MAX_POSITIONS -
            len(positions)
        )

        if available_slots <= 0:
            continue

        signals = today[
            today["Signal"] == True
        ].copy()

        held = {
            pos["Ticker"]
            for pos in positions
        }

        signals = signals[
            ~signals["Ticker"].isin(held)
        ]

        # Même ordre de sélection V5.1 :
        # ATR puis Return10.
        signals = signals.sort_values(
            [
                "ATR_Pct",
                "Return_10D",
                "Ticker"
            ],
            ascending=[
                False,
                False,
                True
            ]
        )

        selected = signals.head(
            available_slots
        )

        # Equity actuelle pour déterminer
        # la taille de position.
        current_equity = cash

        for pos in positions:

            price = prices.get(
                pos["Ticker"]
            )

            if price is not None and not pd.isna(price):

                current_equity += (
                    pos["shares"] *
                    float(price)
                )

        target_value = (
            current_equity *
            allocation
        )

        for _, row in selected.iterrows():

            entry_raw = float(
                row["Open"]
            )

            if pd.isna(entry_raw) or entry_raw <= 0:
                continue

            entry_price = (
                entry_raw *
                (1.0 + BUY_SLIPPAGE)
            )

            # Coût total maximum par action
            # incluant les frais.
            total_price = (
                entry_price *
                (1.0 + BUY_FEE)
            )

            shares_target = (
                target_value /
                total_price
            )

            shares_affordable = (
                cash /
                total_price
            )

            shares = min(
                shares_target,
                shares_affordable
            )

            if shares <= 0:
                cash_blocked += 1
                continue

            gross_cost = (
                shares *
                entry_price
            )

            buy_fee = (
                gross_cost *
                BUY_FEE
            )

            total_cost = (
                gross_cost +
                buy_fee
            )

            if total_cost > cash + 1e-9:

                cash_blocked += 1
                continue

            cash -= total_cost

            positions.append(
                {
                    "Ticker": row["Ticker"],
                    "entry_date": current_date,
                    "entry_index": current_index,
                    "entry_price": entry_price,
                    "shares": shares,
                    "cash_deployed": total_cost
                }
            )

            max_positions_seen = max(
                max_positions_seen,
                len(positions)
            )

    # ------------------------------------------------------
    # 4. LIQUIDATION FINALE
    # ------------------------------------------------------

    final_date = pd.Timestamp(
        dates[-1]
    )

    final_rows = df[
        df["Date"] == final_date
    ]

    for pos in positions:

        row = final_rows[
            final_rows["Ticker"] ==
            pos["Ticker"]
        ]

        if len(row) == 0:
            continue

        exit_raw = float(
            row.iloc[0]["Close"]
        )

        if pd.isna(exit_raw):
            continue

        exit_price = (
            exit_raw *
            (1.0 - SELL_SLIPPAGE)
        )

        gross_value = (
            pos["shares"] *
            exit_price
        )

        sell_fee = (
            gross_value *
            SELL_FEE
        )

        proceeds = (
            gross_value -
            sell_fee
        )

        cash += proceeds

        pnl = (
            proceeds -
            pos["cash_deployed"]
        )

        trades.append(
            {
                "Ticker": pos["Ticker"],
                "Entry_Date": pos["entry_date"],
                "Exit_Date": final_date,
                "Entry_Price": pos["entry_price"],
                "Exit_Price": exit_price,
                "Shares": pos["shares"],
                "Cash_Deployed": pos["cash_deployed"],
                "PnL": pnl,
                "Return": (
                    pnl /
                    pos["cash_deployed"]
                )
            }
        )

    trades_df = pd.DataFrame(
        trades
    )

    final_equity = cash

    if len(trades_df) > 0:

        wins = (
            trades_df["PnL"] > 0
        ).sum()

        gross_profit = trades_df.loc[
            trades_df["PnL"] > 0,
            "PnL"
        ].sum()

        gross_loss = -trades_df.loc[
            trades_df["PnL"] < 0,
            "PnL"
        ].sum()

        profit_factor = (
            gross_profit /
            gross_loss
            if gross_loss > 0
            else np.inf
        )

        win_rate = (
            wins /
            len(trades_df)
        )

        avg_trade = (
            trades_df["Return"].mean()
        )

        median_trade = (
            trades_df["Return"].median()
        )

    else:

        win_rate = np.nan
        profit_factor = np.nan
        avg_trade = np.nan
        median_trade = np.nan

    # Equity finale = liquidation finale.
    if len(equity_curve) > 0:

        equity_df = pd.DataFrame(
            equity_curve
        )

        equity_df.loc[
            equity_df.index[-1],
            "Equity"
        ] = final_equity

        dd = max_drawdown(
            equity_df["Equity"]
        )

    else:

        dd = 0.0

    return {
        "allocation": allocation,
        "trades": len(trades_df),
        "win_rate": win_rate,
        "pnl": trades_df["PnL"].sum()
        if len(trades_df)
        else 0.0,
        "return_pct": (
            final_equity /
            INITIAL_CAPITAL -
            1
        ) * 100,
        "avg_trade_pct": avg_trade * 100,
        "median_trade_pct": median_trade * 100,
        "profit_factor": profit_factor,
        "max_drawdown_pct": dd * 100,
        "max_positions": max_positions_seen,
        "cash_blocked_signals": cash_blocked
    }


def main():

    print("=" * 80)
    print("MOMENTUM V1 — SIZING SENSITIVITY — PROTOCOLE V5.1")
    print("=" * 80)

    df = prepare_data()

    print(
        f"Dataset : {len(df):,} lignes"
    )

    print(
        f"Actions : {df['Ticker'].nunique()}"
    )

    print(
        f"Période : "
        f"{df['Date'].min().date()} -> "
        f"{df['Date'].max().date()}"
    )

    print("\nSEUILS WALK-FORWARD V5.1")
    print("-" * 80)

    thresholds = build_v5_1_thresholds(
        df
    )

    results = []

    print("\n")
    print("=" * 80)
    print("TEST DES SIZINGS")
    print("=" * 80)

    for allocation in SIZINGS:

        print(
            f"\nAllocation = "
            f"{allocation * 100:.0f}%"
        )

        result = run_backtest(
            df,
            thresholds,
            allocation
        )

        results.append(result)

        print(
            f"Trades        : {result['trades']}"
        )

        print(
            f"Win rate      : "
            f"{result['win_rate'] * 100:.2f}%"
        )

        print(
            f"PnL           : "
            f"${result['pnl']:,.2f}"
        )

        print(
            f"Return        : "
            f"{result['return_pct']:.2f}%"
        )

        print(
            f"Avg trade     : "
            f"{result['avg_trade_pct']:.3f}%"
        )

        print(
            f"Median trade  : "
            f"{result['median_trade_pct']:.3f}%"
        )

        print(
            f"Profit Factor : "
            f"{result['profit_factor']:.2f}"
        )

        print(
            f"Max DD        : "
            f"{result['max_drawdown_pct']:.2f}%"
        )

        print(
            f"Max positions : "
            f"{result['max_positions']}"
        )

        print(
            f"Cash blocked  : "
            f"{result['cash_blocked_signals']}"
        )

    results_df = pd.DataFrame(
        results
    )

    output_path = Path(
        "results/momentum/"
        "momentum_v1_sizing_v5_1.csv"
    )

    results_df.to_csv(
        output_path,
        index=False
    )

    print("\n")
    print("=" * 80)
    print("TABLEAU FINAL")
    print("=" * 80)

    print(
        results_df[
            [
                "allocation",
                "trades",
                "win_rate",
                "pnl",
                "return_pct",
                "profit_factor",
                "max_drawdown_pct",
                "max_positions",
                "cash_blocked_signals"
            ]
        ].to_string(index=False)
    )

    print(
        f"\nSauvegardé : {output_path}"
    )


if __name__ == "__main__":
    main()
