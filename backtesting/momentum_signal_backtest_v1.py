from pathlib import Path
import pandas as pd
import numpy as np

DATA_FILE = Path("results/momentum/momentum_v1_research.csv")
INITIAL_CAPITAL = 10_000.0
POSITION_PCT = 0.20
MAX_POSITIONS = 5
HOLDING_PERIODS = [1, 3, 5]
TRAIN_QUANTILE = 0.80

TRADES_OUTPUT = Path("results/momentum/momentum_signal_v1_trades.csv")
EQUITY_OUTPUT = Path("results/momentum/momentum_signal_v1_equity.csv")
SUMMARY_OUTPUT = Path("results/momentum/momentum_signal_v1_summary.csv")

WALK_FORWARD_WINDOWS = [
    ("2018-10-16", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("2019-01-02", "2022-12-30", "2023-01-01", "2023-12-31"),
    ("2020-01-02", "2023-12-29", "2024-01-01", "2024-12-31"),
    ("2021-01-04", "2024-12-31", "2025-01-01", "2025-12-31"),
]

print("=" * 70)
print("MOMENTUM V1 - SIGNAL ONLY BACKTEST")
print("=" * 70)

if not DATA_FILE.exists():
    print(f"ERREUR : fichier introuvable : {DATA_FILE}")
    raise SystemExit(1)

df = pd.read_csv(DATA_FILE)
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

required = [
    "Date", "Ticker", "Open", "High", "Low", "Close",
    "ATR_Pct", "Return_10D"
]

missing = [c for c in required if c not in df.columns]

if missing:
    print("ERREUR : colonnes manquantes :", missing)
    raise SystemExit(1)

for col in ["Open", "High", "Low", "Close", "ATR_Pct", "Return_10D"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = (
    df[required]
    .dropna()
    .sort_values(["Ticker", "Date"])
    .reset_index(drop=True)
)

print(f"Dataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")
print(f"Période : {df['Date'].min().date()} -> {df['Date'].max().date()}")

# ------------------------------------------------------------
# Préparation : index de séance pour chaque action
# ------------------------------------------------------------

stocks = {}

for ticker, group in df.groupby("Ticker"):
    group = group.sort_values("Date").reset_index(drop=True).copy()
    group["Session_Index"] = np.arange(len(group))
    stocks[ticker] = group


def run_window(train_start, train_end, test_start, test_end, hold_days):

    train_start = pd.Timestamp(train_start)
    train_end = pd.Timestamp(train_end)
    test_start = pd.Timestamp(test_start)
    test_end = pd.Timestamp(test_end)

    train = df[
        (df["Date"] >= train_start) &
        (df["Date"] <= train_end)
    ]

    test = df[
        (df["Date"] >= test_start) &
        (df["Date"] <= test_end)
    ]

    if train.empty or test.empty:
        return [], []

    atr_threshold = train["ATR_Pct"].quantile(TRAIN_QUANTILE)
    return10_threshold = train["Return_10D"].quantile(TRAIN_QUANTILE)

    print(
        f"\nWindow {test_start.year} | "
        f"Hold {hold_days} séance(s)"
    )
    print(f"ATR Q80      : {atr_threshold:.6f}")
    print(f"Return10 Q80 : {return10_threshold:.6f}")

    dates = sorted(test["Date"].unique())
    test_by_date = {
        date: group.copy()
        for date, group in test.groupby("Date")
    }

    cash = INITIAL_CAPITAL
    positions = []
    pending = []
    trades = []
    equity_records = []

    # Pour chaque ticker, on garde les lignes du test
    # avec leur index de séance.
    test_stocks = {}

    for ticker, group in test.groupby("Ticker"):
        test_stocks[ticker] = (
            group.sort_values("Date")
            .reset_index(drop=True)
            .copy()
        )

    for current_date in dates:

        current_date = pd.Timestamp(current_date)
        today = test_by_date[current_date]

        # ====================================================
        # 1. ENTRÉES À L'OPEN
        # ====================================================

        entries = [
            x for x in pending
            if x["Entry_Date"] == current_date
        ]

        pending = [
            x for x in pending
            if x["Entry_Date"] != current_date
        ]

        slots = MAX_POSITIONS - len(positions)

        if slots > 0 and entries:

            for signal in entries:
                signal["Strength"] = (
                    signal["ATR_Pct"] / atr_threshold
                    + signal["Return_10D"] / return10_threshold
                )

            entries.sort(
                key=lambda x: x["Strength"],
                reverse=True
            )

            entries = entries[:slots]

            for signal in entries:

                ticker = signal["Ticker"]

                row = today[
                    today["Ticker"] == ticker
                ]

                if row.empty:
                    continue

                row = row.iloc[0]
                entry_price = float(row["Open"])

                if not np.isfinite(entry_price) or entry_price <= 0:
                    continue

                # Equity disponible au moment de l'entrée
                market_value = sum(
                    p["Shares"] * p["Current_Price"]
                    for p in positions
                )

                equity = cash + market_value

                position_value = min(
                    equity * POSITION_PCT,
                    cash
                )

                if position_value <= 0:
                    continue

                shares = position_value / entry_price

                cash -= position_value

                # Index de séance du jour d'entrée
                ticker_test = test_stocks[ticker]

                matching = ticker_test[
                    ticker_test["Date"] == current_date
                ]

                if matching.empty:
                    continue

                entry_index = int(
                    matching.iloc[0].name
                )

                positions.append({
                    "Ticker": ticker,
                    "Signal_Date": signal["Signal_Date"],
                    "Entry_Date": current_date,
                    "Entry_Index": entry_index,
                    "Entry_Price": entry_price,
                    "Shares": shares,
                    "Position_Value": position_value,
                    "ATR_Pct": signal["ATR_Pct"],
                    "Return_10D": signal["Return_10D"],
                    "Current_Price": entry_price,
                })

        # ====================================================
        # 2. PRIX DE CLÔTURE
        # ====================================================

        close_prices = {
            row["Ticker"]: float(row["Close"])
            for _, row in today.iterrows()
        }

        for position in positions:
            ticker = position["Ticker"]

            if ticker in close_prices:
                position["Current_Price"] = close_prices[ticker]

        # ====================================================
        # 3. SORTIE APRÈS N SÉANCES
        # ====================================================

        remaining = []

        for position in positions:

            ticker = position["Ticker"]

            ticker_test = test_stocks[ticker]

            matching = ticker_test[
                ticker_test["Date"] == current_date
            ]

            if matching.empty:
                remaining.append(position)
                continue

            current_index = int(matching.iloc[0].name)

            sessions_held = (
                current_index
                - position["Entry_Index"]
                + 1
            )

            if sessions_held >= hold_days:

                exit_price = position["Current_Price"]

                pnl = (
                    exit_price
                    - position["Entry_Price"]
                ) * position["Shares"]

                trade_return = (
                    exit_price
                    / position["Entry_Price"]
                    - 1
                )

                cash += (
                    position["Shares"]
                    * exit_price
                )

                trades.append({
                    "Ticker": ticker,
                    "Signal_Date": position["Signal_Date"],
                    "Entry_Date": position["Entry_Date"],
                    "Exit_Date": current_date,
                    "Entry_Price": position["Entry_Price"],
                    "Exit_Price": exit_price,
                    "Shares": position["Shares"],
                    "Position_Value": position["Position_Value"],
                    "PnL": pnl,
                    "Return": trade_return,
                    "Hold_Days": sessions_held,
                    "ATR_Pct": position["ATR_Pct"],
                    "Return_10D": position["Return_10D"],
                    "Exit_Reason": f"TIME_{hold_days}",
                })

            else:
                remaining.append(position)

        positions = remaining

        # ====================================================
        # 4. SIGNALS À LA CLÔTURE
        # ====================================================

        for _, row in today.iterrows():

            ticker = row["Ticker"]
            atr = float(row["ATR_Pct"])
            return10 = float(row["Return_10D"])

            if (
                not np.isfinite(atr)
                or not np.isfinite(return10)
            ):
                continue

            if (
                atr < atr_threshold
                or return10 < return10_threshold
            ):
                continue

            # Pas de deuxième position sur la même action
            if any(
                p["Ticker"] == ticker
                for p in positions
            ):
                continue

            # Pas de signal déjà en attente
            if any(
                p["Ticker"] == ticker
                for p in pending
            ):
                continue

            ticker_test = test_stocks.get(ticker)

            if ticker_test is None:
                continue

            future = ticker_test[
                ticker_test["Date"] > current_date
            ]

            if future.empty:
                continue

            entry_date = future.iloc[0]["Date"]

            pending.append({
                "Ticker": ticker,
                "Signal_Date": current_date,
                "Entry_Date": entry_date,
                "ATR_Pct": atr,
                "Return_10D": return10,
            })

        # ====================================================
        # 5. EQUITY QUOTIDIENNE
        # ====================================================

        market_value = sum(
            p["Shares"] * p["Current_Price"]
            for p in positions
        )

        equity = cash + market_value

        equity_records.append({
            "Date": current_date,
            "Equity": equity,
            "Cash": cash,
            "Open_Positions": len(positions),
        })

    return trades, equity_records


# ============================================================
# LANCEMENT DES TESTS
# ============================================================

all_trades = []
all_equity = []

for train_start, train_end, test_start, test_end in WALK_FORWARD_WINDOWS:

    for hold_days in HOLDING_PERIODS:

        trades, equity = run_window(
            train_start,
            train_end,
            test_start,
            test_end,
            hold_days
        )

        for trade in trades:
            trade["Window"] = pd.Timestamp(test_start).year
            trade["Holding_Period"] = hold_days

        for row in equity:
            row["Window"] = pd.Timestamp(test_start).year
            row["Holding_Period"] = hold_days

        all_trades.extend(trades)
        all_equity.extend(equity)


trades_df = pd.DataFrame(all_trades)
equity_df = pd.DataFrame(all_equity)

TRADES_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

trades_df.to_csv(TRADES_OUTPUT, index=False)
equity_df.to_csv(EQUITY_OUTPUT, index=False)


# ============================================================
# RÉSULTATS
# ============================================================

summary = []

print("\n")
print("=" * 70)
print("RÉSULTATS")
print("=" * 70)

for hold_days in HOLDING_PERIODS:

    subset = trades_df[
        trades_df["Holding_Period"] == hold_days
    ]

    if subset.empty:
        continue

    pnl = subset["PnL"]

    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]

    gross_profit = winners.sum()
    gross_loss = abs(losers.sum())

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    win_rate = (pnl > 0).mean()
    total_pnl = pnl.sum()

    eq = equity_df[
        equity_df["Holding_Period"] == hold_days
    ].copy()

    worst_dd = 0.0

    for _, window_eq in eq.groupby("Window"):

        window_eq = window_eq.sort_values("Date")

        values = window_eq["Equity"]

        peak = values.cummax()

        dd = values / peak - 1

        if not dd.empty:
            worst_dd = min(
                worst_dd,
                dd.min()
            )

    print(f"\nHOLD {hold_days} SÉANCE(S)")
    print("-" * 50)
    print(f"Trades             : {len(subset):,}")
    print(f"Win rate           : {win_rate * 100:.2f}%")
    print(f"PnL                : ${total_pnl:,.2f}")
    print(f"Return portefeuille: {total_pnl / INITIAL_CAPITAL * 100:.2f}%")
    print(f"Trade moyen        : {subset['Return'].mean() * 100:.3f}%")
    print(f"Trade médian       : {subset['Return'].median() * 100:.3f}%")
    print(f"Profit Factor      : {pf:.2f}")
    print(f"Max DD             : {worst_dd * 100:.2f}%")

    summary.append({
        "Holding_Period": hold_days,
        "Trades": len(subset),
        "Win_Rate": win_rate,
        "PnL": total_pnl,
        "Return": total_pnl / INITIAL_CAPITAL,
        "Avg_Trade_Return": subset["Return"].mean(),
        "Median_Trade_Return": subset["Return"].median(),
        "Profit_Factor": pf,
        "Max_Drawdown": worst_dd,
    })


# ============================================================
# PAR ANNÉE
# ============================================================

print("\n")
print("=" * 70)
print("PERFORMANCE PAR ANNÉE")
print("=" * 70)

for hold_days in HOLDING_PERIODS:

    subset = trades_df[
        trades_df["Holding_Period"] == hold_days
    ].copy()

    if subset.empty:
        continue

    subset["Year"] = pd.to_datetime(
        subset["Exit_Date"]
    ).dt.year

    yearly = subset.groupby("Year").agg(
        Trades=("PnL", "size"),
        PnL=("PnL", "sum"),
        Avg_Return=("Return", "mean"),
        Win_Rate=(
            "PnL",
            lambda x: (x > 0).mean()
        ),
    )

    print(f"\n--- HOLD {hold_days} ---")
    print(yearly.to_string())


# ============================================================
# WALK FORWARD
# ============================================================

print("\n")
print("=" * 70)
print("WALK-FORWARD")
print("=" * 70)

for hold_days in HOLDING_PERIODS:

    subset = trades_df[
        trades_df["Holding_Period"] == hold_days
    ]

    if subset.empty:
        continue

    wf = subset.groupby("Window").agg(
        Trades=("PnL", "size"),
        PnL=("PnL", "sum"),
        Avg_Return=("Return", "mean"),
        Win_Rate=(
            "PnL",
            lambda x: (x > 0).mean()
        ),
    )

    print(f"\n--- HOLD {hold_days} ---")
    print(wf.to_string())


summary_df = pd.DataFrame(summary)
summary_df.to_csv(SUMMARY_OUTPUT, index=False)

print("\n")
print("=" * 70)
print("FICHIERS CRÉÉS")
print("=" * 70)
print(TRADES_OUTPUT)
print(EQUITY_OUTPUT)
print(SUMMARY_OUTPUT)

print("\nFIN")
print("=" * 70)
