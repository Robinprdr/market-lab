import pandas as pd
import numpy as np

INPUT = "results/short_momentum/short_momentum_v1_research.csv"

INITIAL_CAPITAL = 10_000.0

# Benchmark provisoire
ALLOCATION = 0.15
MAX_POSITIONS = 5

FEE_RATE = 0.0005
SLIPPAGE_RATE = 0.0005

HOLD_DAYS_LIST = [1, 3, 5]

TRAIN_START = "2018-10-16"

TEST_YEARS = {
    2022: ("2022-01-01", "2022-12-31"),
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-05"),
}


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(INPUT)
df["Date"] = pd.to_datetime(df["Date"])

df = df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

dates = sorted(df["Date"].unique())
date_to_index = {pd.Timestamp(d): i for i, d in enumerate(dates)}

print("=" * 90)
print("SHORT MOMENTUM V1 — PORTFOLIO BACKTEST V2")
print("=" * 90)
print()

print(f"Capital initial : ${INITIAL_CAPITAL:,.2f}")
print(f"Allocation      : {ALLOCATION:.0%}")
print(f"Max positions   : {MAX_POSITIONS}")
print(f"Frais           : {FEE_RATE:.2%} par côté")
print(f"Slippage        : {SLIPPAGE_RATE:.2%} par côté")
print()

print("ALIGNEMENT DU TRADE :")
print("Signal T -> entrée Open T+1 -> sortie Close T+N")
print()


# ============================================================
# FONCTIONS
# ============================================================

def get_row(date, ticker):
    rows = df[
        (df["Date"] == date) &
        (df["Ticker"] == ticker)
    ]

    if len(rows) == 0:
        return None

    return rows.iloc[0]


def calculate_equity(cash, positions, date):

    equity = cash

    for position in positions:

        row = get_row(date, position["Ticker"])

        if row is None:
            equity += position["margin"]
            continue

        close_price = row["Close"]

        unrealized_pnl = (
            position["shares"] *
            (position["entry_price"] - close_price)
        )

        equity += (
            position["margin"] +
            unrealized_pnl
        )

    return equity


def analyze_trades(trades_df):

    if len(trades_df) == 0:
        return None

    pnl = trades_df["PnL"]

    win_rate = (pnl > 0).mean()

    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    return {
        "trades": len(trades_df),
        "win_rate": win_rate,
        "avg_trade": trades_df["Return"].mean(),
        "median_trade": trades_df["Return"].median(),
        "profit_factor": profit_factor,
    }


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(hold_days):

    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    equity_curve = []

    for date_idx, date_raw in enumerate(dates):

        date = pd.Timestamp(date_raw)

        # ----------------------------------------------------
        # 1. FERMETURES
        # ----------------------------------------------------

        remaining_positions = []

        for position in positions:

            if date < position["exit_date"]:
                remaining_positions.append(position)
                continue

            row = get_row(date, position["Ticker"])

            if row is None:
                remaining_positions.append(position)
                continue

            exit_close = row["Close"]

            # Pour un short :
            # on rachète légèrement plus cher
            effective_exit = (
                exit_close *
                (1 + SLIPPAGE_RATE)
            )

            gross_pnl = (
                position["shares"] *
                (position["entry_price"] - effective_exit)
            )

            exit_value = (
                position["shares"] *
                effective_exit
            )

            exit_fee = exit_value * FEE_RATE

            pnl = (
                gross_pnl
                - exit_fee
                - position["entry_fee"]
            )

            cash += (
                position["margin"]
                + pnl
            )

            trades.append({
                "Ticker": position["Ticker"],
                "Entry_Date": position["entry_date"],
                "Exit_Date": date,
                "Entry_Price": position["entry_price"],
                "Exit_Price": effective_exit,
                "Shares": position["shares"],
                "Margin": position["margin"],
                "PnL": pnl,
                "Return": pnl / position["margin"],
                "Hold_Days": hold_days,
            })

        positions = remaining_positions

        # ----------------------------------------------------
        # 2. EQUITY AVANT NOUVELLES ENTRÉES
        # ----------------------------------------------------

        equity_before_entries = calculate_equity(
            cash,
            positions,
            date
        )

        # ----------------------------------------------------
        # 3. SIGNALS DU JOUR
        # ----------------------------------------------------

        year = date.year

        if year not in TEST_YEARS:

            equity_curve.append({
                "Date": date,
                "Equity": equity_before_entries
            })

            continue

        test_start = pd.Timestamp(
            TEST_YEARS[year][0]
        )

        # Historique strictement antérieur
        train = df[
            (df["Date"] >= TRAIN_START) &
            (df["Date"] < test_start)
        ]

        atr_threshold = train["ATR_Pct"].quantile(0.80)
        ret_threshold = train["Return_3D"].quantile(0.20)

        day_data = df[
            df["Date"] == date
        ].copy()

        signals = day_data[
            (day_data["ATR_Pct"] >= atr_threshold) &
            (day_data["Return_3D"] <= ret_threshold)
        ].copy()

        # SPY est seulement un facteur, jamais une position
        signals = signals[
            signals["Ticker"] != "SPY"
        ]

        # Priorité :
        # ATR le plus élevé
        # puis Return_3D le plus négatif
        signals = signals.sort_values(
            ["ATR_Pct", "Return_3D"],
            ascending=[False, True]
        )

        # ----------------------------------------------------
        # 4. DATE D'ENTRÉE = JOUR SUIVANT
        # ----------------------------------------------------

        if date_idx + 1 >= len(dates):

            equity_curve.append({
                "Date": date,
                "Equity": equity_before_entries
            })

            continue

        entry_idx = date_idx + 1
        entry_date = pd.Timestamp(dates[entry_idx])

        current_tickers = {
            p["Ticker"]
            for p in positions
        }

        available_slots = (
            MAX_POSITIONS -
            len(positions)
        )

        # ----------------------------------------------------
        # 5. NOUVELLES POSITIONS
        # ----------------------------------------------------

        for _, signal in signals.iterrows():

            if available_slots <= 0:
                break

            ticker = signal["Ticker"]

            if ticker in current_tickers:
                continue

            entry_row = get_row(
                entry_date,
                ticker
            )

            if entry_row is None:
                continue

            entry_open = entry_row["Open"]

            if pd.isna(entry_open) or entry_open <= 0:
                continue

            # ------------------------------------------------
            # IMPORTANT :
            # pour un SHORT, le slippage rend la vente
            # légèrement moins favorable :
            # prix d'entrée légèrement PLUS BAS ?
            #
            # Correction :
            # Une vente short exécutée avec slippage défavorable
            # reçoit un prix légèrement plus BAS.
            # ------------------------------------------------

            effective_entry = (
                entry_open *
                (1 - SLIPPAGE_RATE)
            )

            # ------------------------------------------------
            # Taille
            # ------------------------------------------------

            position_value = (
                equity_before_entries *
                ALLOCATION
            )

            if position_value <= 0:
                continue

            shares = (
                position_value /
                effective_entry
            )

            entry_value = (
                shares *
                effective_entry
            )

            entry_fee = (
                entry_value *
                FEE_RATE
            )

            required_cash = (
                position_value +
                entry_fee
            )

            if required_cash > cash:
                continue

            cash -= required_cash

            # ------------------------------------------------
            # CORRECTION IMPORTANTE DU HOLD
            #
            # Signal T
            # Entry T+1
            #
            # hold=1 -> sortie Close T+1
            # hold=3 -> sortie Close T+3
            # hold=5 -> sortie Close T+5
            #
            # Donc depuis entry_idx :
            # exit_idx = entry_idx + hold_days - 1
            # ------------------------------------------------

            exit_idx = (
                entry_idx +
                hold_days -
                1
            )

            if exit_idx >= len(dates):

                # Si impossible de calculer une sortie,
                # on annule proprement l'entrée.
                cash += required_cash
                continue

            exit_date = pd.Timestamp(
                dates[exit_idx]
            )

            positions.append({
                "Ticker": ticker,
                "entry_date": entry_date,
                "entry_price": effective_entry,
                "shares": shares,
                "margin": position_value,
                "entry_fee": entry_fee,
                "exit_date": exit_date,
            })

            current_tickers.add(ticker)

            available_slots -= 1

        # ----------------------------------------------------
        # 6. EQUITY FIN DE JOURNÉE
        # ----------------------------------------------------

        equity_end = calculate_equity(
            cash,
            positions,
            date
        )

        equity_curve.append({
            "Date": date,
            "Equity": equity_end
        })

    # ========================================================
    # LIQUIDATION FINALE
    # ========================================================

    final_date = pd.Timestamp(dates[-1])

    for position in positions:

        row = get_row(
            final_date,
            position["Ticker"]
        )

        if row is None:
            continue

        exit_close = row["Close"]

        effective_exit = (
            exit_close *
            (1 + SLIPPAGE_RATE)
        )

        gross_pnl = (
            position["shares"] *
            (position["entry_price"] - effective_exit)
        )

        exit_value = (
            position["shares"] *
            effective_exit
        )

        exit_fee = (
            exit_value *
            FEE_RATE
        )

        pnl = (
            gross_pnl
            - exit_fee
            - position["entry_fee"]
        )

        cash += (
            position["margin"]
            + pnl
        )

        trades.append({
            "Ticker": position["Ticker"],
            "Entry_Date": position["entry_date"],
            "Exit_Date": final_date,
            "Entry_Price": position["entry_price"],
            "Exit_Price": effective_exit,
            "Shares": position["shares"],
            "Margin": position["margin"],
            "PnL": pnl,
            "Return": pnl / position["margin"],
            "Hold_Days": hold_days,
        })

    # ========================================================
    # STATISTIQUES
    # ========================================================

    trades_df = pd.DataFrame(trades)

    if len(trades_df) == 0:
        return None

    final_equity = cash

    total_return = (
        final_equity /
        INITIAL_CAPITAL
        - 1
    )

    stats = analyze_trades(trades_df)

    equity_df = pd.DataFrame(
        equity_curve
    )

    equity_df["Peak"] = (
        equity_df["Equity"]
        .cummax()
    )

    equity_df["Drawdown"] = (
        equity_df["Equity"] /
        equity_df["Peak"]
        - 1
    )

    max_drawdown = (
        equity_df["Drawdown"]
        .min()
    )

    return {
        "hold_days": hold_days,
        "trades_df": trades_df,
        "equity_df": equity_df,
        "final_equity": final_equity,
        "pnl": final_equity - INITIAL_CAPITAL,
        "return": total_return,
        "max_drawdown": max_drawdown,
        **stats,
    }


# ============================================================
# EXÉCUTION
# ============================================================

results = []

for hold_days in HOLD_DAYS_LIST:

    print("=" * 90)
    print(f"BACKTEST — HOLD {hold_days} JOUR(S)")
    print("=" * 90)
    print()

    result = run_backtest(
        hold_days
    )

    if result is None:
        print("Aucun trade.")
        print()
        continue

    results.append(result)

    print(f"Trades          : {result['trades']:,}")
    print(f"Win rate        : {result['win_rate']:.2%}")
    print(f"PnL             : ${result['pnl']:,.2f}")
    print(f"Capital final   : ${result['final_equity']:,.2f}")
    print(f"Return          : {result['return']:.2%}")
    print(f"Trade moyen     : {result['avg_trade']:.3%}")
    print(f"Trade médian    : {result['median_trade']:.3%}")
    print(f"Profit Factor   : {result['profit_factor']:.2f}")
    print(f"Max Drawdown    : {result['max_drawdown']:.2%}")
    print()

    # --------------------------------------------------------
    # ANNUEL
    # --------------------------------------------------------

    trades_df = result["trades_df"].copy()

    trades_df["Year"] = pd.to_datetime(
        trades_df["Exit_Date"]
    ).dt.year

    print("Performance annuelle :")

    for year, group in trades_df.groupby("Year"):

        pnl = group["PnL"].sum()
        wr = (group["PnL"] > 0).mean()

        print(
            f"  {year} : "
            f"${pnl:+,.2f} | "
            f"WR {wr:.1%} | "
            f"{len(group)} trades"
        )

    print()

    # --------------------------------------------------------
    # TOP / FLOP TICKERS
    # --------------------------------------------------------

    by_ticker = (
        trades_df
        .groupby("Ticker")["PnL"]
        .sum()
        .sort_values(ascending=False)
    )

    print("Top 10 contributions :")

    for ticker, pnl in by_ticker.head(10).items():
        print(
            f"  {ticker:<6} "
            f"${pnl:+,.2f}"
        )

    print()

    print("Bottom 10 contributions :")

    for ticker, pnl in by_ticker.tail(10).items():
        print(
            f"  {ticker:<6} "
            f"${pnl:+,.2f}"
        )

    print()


# ============================================================
# RÉSUMÉ
# ============================================================

summary = []

for result in results:

    summary.append({
        "Hold_Days": result["hold_days"],
        "Trades": result["trades"],
        "Win_Rate": result["win_rate"],
        "PnL": result["pnl"],
        "Final_Equity": result["final_equity"],
        "Return": result["return"],
        "Avg_Trade": result["avg_trade"],
        "Median_Trade": result["median_trade"],
        "Profit_Factor": result["profit_factor"],
        "Max_Drawdown": result["max_drawdown"],
    })

summary_df = pd.DataFrame(summary)

summary_path = (
    "results/short_momentum/"
    "short_momentum_v1_portfolio_summary.csv"
)

summary_df.to_csv(
    summary_path,
    index=False
)

for result in results:

    trade_path = (
        "results/short_momentum/"
        f"short_momentum_v1_portfolio_"
        f"{result['hold_days']}d_trades.csv"
    )

    result["trades_df"].to_csv(
        trade_path,
        index=False
    )

print("=" * 90)
print("RÉSUMÉ FINAL")
print("=" * 90)
print()

print(
    summary_df.to_string(
        index=False
    )
)

print()
print(
    f"Résumé sauvegardé : "
    f"{summary_path}"
)
