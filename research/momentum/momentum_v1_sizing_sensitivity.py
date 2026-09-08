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


def prepare_data():
    df = pd.read_csv(DATA_PATH, parse_dates=["Date"])

    df = df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    print(f"Dataset : {len(df):,} lignes")
    print(f"Actions : {df['Ticker'].nunique()}")
    print(
        f"Période : "
        f"{df['Date'].min().date()} -> {df['Date'].max().date()}"
    )

    # On garde tout l'historique pour calculer les seuils walk-forward.
    return df


def build_thresholds(df):
    thresholds = {}

    for year in range(2022, 2026):
        train_end = pd.Timestamp(f"{year - 1}-12-31")
        test_start = pd.Timestamp(f"{year}-01-01")
        test_end = pd.Timestamp(f"{year}-12-31")

        train = df[df["Date"] <= train_end].copy()

        atr_threshold = q80(train["ATR_Pct"])
        ret10_threshold = q80(train["Return_10D"])

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
            f"ATR Q80={atr_threshold:.6f}, "
            f"Return10 Q80={ret10_threshold:.6f}, "
            f"test rows={len(test_rows):,}"
        )

    return thresholds


def max_drawdown(equity_curve):
    if len(equity_curve) == 0:
        return 0.0

    equity = pd.Series(equity_curve, dtype=float)
    peak = equity.cummax()
    dd = equity / peak - 1.0

    return float(dd.min())


def run_backtest(df, thresholds, allocation):
    df = df.copy()

    # Test period seulement après avoir calculé les seuils.
    df = df[
        (df["Date"] >= pd.Timestamp(START_DATE)) &
        (df["Date"] <= pd.Timestamp(END_DATE))
    ].copy()

    # Prépare les signaux.
    df["Signal"] = False

    for year, threshold in thresholds.items():
        mask_year = df["Date"].dt.year == year

        df.loc[mask_year, "Signal"] = (
            (df.loc[mask_year, "ATR_Pct"] >= threshold["atr"]) &
            (df.loc[mask_year, "Return_10D"] >= threshold["ret10"])
        )

    # Chaque ligne correspond au signal observé à la clôture.
    # Entrée au prochain OPEN.
    df = df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    # Index par date pour accès rapide au prochain jour.
    dates = sorted(df["Date"].dropna().unique())
    date_to_idx = {date: i for i, date in enumerate(dates)}

    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    equity_curve = []

    cash_blocked_signals = 0
    max_positions_seen = 0

    for current_date in dates:
        current_date = pd.Timestamp(current_date)

        # ---------------------------------------------------------
        # 1. VALORISATION DES POSITIONS
        # ---------------------------------------------------------
        today_rows = df[df["Date"] == current_date]

        prices = dict(
            zip(
                today_rows["Ticker"],
                today_rows["Close"]
            )
        )

        equity = cash

        for pos in positions:
            price = prices.get(pos["Ticker"])

            if price is not None and not pd.isna(price):
                equity += pos["shares"] * float(price)

        equity_curve.append(
            {
                "Date": current_date,
                "Equity": equity,
            }
        )

        # ---------------------------------------------------------
        # 2. SORTIES APRES HOLD_DAYS
        # ---------------------------------------------------------
        remaining_positions = []

        for pos in positions:
            entry_index = pos["entry_date_index"]

            current_index = date_to_idx[current_date]

            holding_days = current_index - entry_index

            if holding_days >= HOLD_DAYS:
                row = today_rows[
                    today_rows["Ticker"] == pos["Ticker"]
                ]

                if len(row) == 0:
                    remaining_positions.append(pos)
                    continue

                exit_price_raw = float(row.iloc[0]["Open"])

                # Si Open n'est pas disponible, on garde la position.
                if pd.isna(exit_price_raw):
                    remaining_positions.append(pos)
                    continue

                exit_price = exit_price_raw * (
                    1.0 - SELL_SLIPPAGE
                )

                gross_value = pos["shares"] * exit_price

                sell_fee = gross_value * SELL_FEE

                proceeds = gross_value - sell_fee

                cash += proceeds

                pnl = (
                    proceeds
                    - pos["cash_deployed"]
                )

                trade_return = (
                    pnl / pos["cash_deployed"]
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
                        "Return": trade_return,
                    }
                )

            else:
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---------------------------------------------------------
        # 3. NOUVEAUX SIGNAUX
        # ---------------------------------------------------------
        if len(positions) < MAX_POSITIONS:
            available_slots = MAX_POSITIONS - len(positions)

            signal_rows = today_rows[
                today_rows["Signal"] == True
            ].copy()

            # Ne pas reprendre une action déjà en portefeuille.
            held_tickers = {
                p["Ticker"]
                for p in positions
            }

            signal_rows = signal_rows[
                ~signal_rows["Ticker"].isin(held_tickers)
            ].copy()

            # Sélection déterministe :
            # ATR d'abord, puis Return10.
            signal_rows = signal_rows.sort_values(
                ["ATR_Pct", "Return_10D", "Ticker"],
                ascending=[False, False, True]
            )

            selected = signal_rows.head(available_slots)

            for _, row in selected.iterrows():

                entry_price_raw = float(row["Open"])

                if pd.isna(entry_price_raw) or entry_price_raw <= 0:
                    continue

                # Allocation basée sur l'equity disponible AVANT entrée.
                current_equity = cash

                for pos in positions:
                    price = prices.get(pos["Ticker"])

                    if price is not None and not pd.isna(price):
                        current_equity += (
                            pos["shares"] * float(price)
                        )

                target_value = current_equity * allocation

                # Coût d'entrée.
                entry_price = entry_price_raw * (
                    1.0 + BUY_SLIPPAGE
                )

                buy_fee_rate = BUY_FEE

                # On veut que :
                # shares * entry_price * (1 + fee) <= cash
                max_affordable = cash / (
                    entry_price * (1.0 + buy_fee_rate)
                )

                target_shares = target_value / (
                    entry_price * (1.0 + buy_fee_rate)
                )

                shares = min(
                    target_shares,
                    max_affordable
                )

                if shares <= 0:
                    cash_blocked_signals += 1
                    continue

                gross_cost = shares * entry_price

                buy_fee = gross_cost * BUY_FEE

                total_cost = gross_cost + buy_fee

                if total_cost > cash:
                    cash_blocked_signals += 1
                    continue

                cash -= total_cost

                positions.append(
                    {
                        "Ticker": row["Ticker"],
                        "entry_date": current_date,
                        "entry_date_index": date_to_idx[current_date],
                        "entry_price": entry_price,
                        "shares": shares,
                        "cash_deployed": total_cost,
                    }
                )

                max_positions_seen = max(
                    max_positions_seen,
                    len(positions)
                )

    # -------------------------------------------------------------
    # 4. LIQUIDATION FINALE
    # -------------------------------------------------------------
    if len(positions) > 0:
        final_date = dates[-1]
        final_rows = df[df["Date"] == final_date]

        for pos in positions:
            row = final_rows[
                final_rows["Ticker"] == pos["Ticker"]
            ]

            if len(row) == 0:
                continue

            exit_price_raw = float(row.iloc[0]["Close"])

            if pd.isna(exit_price_raw):
                continue

            exit_price = exit_price_raw * (
                1.0 - SELL_SLIPPAGE
            )

            gross_value = pos["shares"] * exit_price
            sell_fee = gross_value * SELL_FEE
            proceeds = gross_value - sell_fee

            cash += proceeds

            pnl = proceeds - pos["cash_deployed"]

            trade_return = (
                pnl / pos["cash_deployed"]
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
                    "Return": trade_return,
                }
            )

    trades_df = pd.DataFrame(trades)

    # Equity finale réelle.
    final_equity = cash

    if len(trades_df) > 0:
        total_pnl = trades_df["PnL"].sum()
        wins = (trades_df["PnL"] > 0).sum()
        losses = (trades_df["PnL"] <= 0).sum()

        gross_profit = trades_df.loc[
            trades_df["PnL"] > 0,
            "PnL"
        ].sum()

        gross_loss = -trades_df.loc[
            trades_df["PnL"] < 0,
            "PnL"
        ].sum()

        pf = (
            gross_profit / gross_loss
            if gross_loss > 0
            else np.inf
        )

        win_rate = wins / len(trades_df)

        avg_trade = trades_df["Return"].mean()

        median_trade = trades_df["Return"].median()

    else:
        total_pnl = 0.0
        wins = 0
        losses = 0
        pf = np.nan
        win_rate = np.nan
        avg_trade = np.nan
        median_trade = np.nan

    equity_df = pd.DataFrame(equity_curve)

    if len(equity_df) > 0:
        # La dernière equity doit refléter la liquidation finale.
        equity_df.loc[
            equity_df.index[-1],
            "Equity"
        ] = final_equity

        dd = max_drawdown(
            equity_df["Equity"].values
        )
    else:
        dd = 0.0

    return {
        "allocation": allocation,
        "trades": len(trades_df),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "pnl": total_pnl,
        "final_equity": final_equity,
        "return_pct": (
            final_equity / INITIAL_CAPITAL - 1.0
        ) * 100.0,
        "avg_trade_pct": avg_trade * 100.0,
        "median_trade_pct": median_trade * 100.0,
        "profit_factor": pf,
        "max_drawdown_pct": dd * 100.0,
        "max_positions": max_positions_seen,
        "cash_blocked_signals": cash_blocked_signals,
    }


def main():
    df = prepare_data()

    thresholds = build_thresholds(df)

    results = []

    print("\n" + "=" * 80)
    print("SENSIBILITE AU SIZING — MOMENTUM V1 — HOLD 3 JOURS")
    print("=" * 80)

    for allocation in SIZINGS:
        print(
            f"\nTest allocation = {allocation * 100:.0f}%..."
        )

        result = run_backtest(
            df,
            thresholds,
            allocation
        )

        results.append(result)

        print(
            f"Trades          : {result['trades']}"
        )
        print(
            f"Win rate        : {result['win_rate'] * 100:.2f}%"
        )
        print(
            f"PnL             : ${result['pnl']:,.2f}"
        )
        print(
            f"Return          : {result['return_pct']:.2f}%"
        )
        print(
            f"Avg trade       : {result['avg_trade_pct']:.3f}%"
        )
        print(
            f"Median trade    : {result['median_trade_pct']:.3f}%"
        )
        print(
            f"Profit Factor   : {result['profit_factor']:.2f}"
        )
        print(
            f"Max DD          : {result['max_drawdown_pct']:.2f}%"
        )
        print(
            f"Max positions   : {result['max_positions']}"
        )
        print(
            f"Cash blocked    : {result['cash_blocked_signals']}"
        )

    results_df = pd.DataFrame(results)

    output_path = Path(
        "results/momentum/"
        "momentum_v1_sizing_sensitivity.csv"
    )

    results_df.to_csv(
        output_path,
        index=False
    )

    print("\n" + "=" * 80)
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
                "cash_blocked_signals",
            ]
        ].to_string(index=False)
    )

    print(
        f"\nRésultat sauvegardé dans : {output_path}"
    )


if __name__ == "__main__":
    main()
