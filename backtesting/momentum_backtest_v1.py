import pandas as pd
import numpy as np
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = Path(
    "results/momentum/momentum_v1_research.csv"
)

TRADES_FILE = Path(
    "results/momentum/momentum_v1_trades.csv"
)

EQUITY_FILE = Path(
    "results/momentum/momentum_v1_equity.csv"
)

INITIAL_CAPITAL = 10_000.0

MAX_POSITIONS = 5

POSITION_SIZE_PCT = 0.20

STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04

MAX_HOLD_DAYS = 3

Q = 0.80


# ============================================================
# WALK-FORWARD WINDOWS
# ============================================================

WINDOWS = [
    ("W1", "2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
    ("W2", "2019-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
    ("W3", "2020-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
    ("W4", "2021-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
]


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("MOMENTUM V1 - PORTFOLIO BACKTEST")
print("=" * 70)

if not INPUT_FILE.exists():
    raise FileNotFoundError(
        f"Fichier introuvable : {INPUT_FILE}"
    )

df = pd.read_csv(INPUT_FILE)

df["Date"] = pd.to_datetime(df["Date"])

df = df.sort_values(
    ["Date", "Ticker"]
).reset_index(drop=True)


# ============================================================
# VERIFICATION DES COLONNES
# ============================================================

required_columns = [
    "Date",
    "Ticker",
    "Open",
    "High",
    "Low",
    "Close",
    "ATR_Pct",
    "Return_10D",
]

missing = [
    col for col in required_columns
    if col not in df.columns
]

if missing:
    raise ValueError(
        f"Colonnes manquantes : {missing}"
    )


print(f"\nDataset : {len(df):,} lignes")
print(f"Actions : {df['Ticker'].nunique()}")
print(
    f"Période : "
    f"{df['Date'].min().date()} -> "
    f"{df['Date'].max().date()}"
)


# ============================================================
# PREPARATION
# ============================================================

df = df.dropna(
    subset=[
        "Open",
        "High",
        "Low",
        "Close",
        "ATR_Pct",
        "Return_10D",
    ]
).copy()


# ============================================================
# VARIABLES DE PORTEFEUILLE
# ============================================================

cash = INITIAL_CAPITAL

positions = {}

trades = []

equity_history = []


# ============================================================
# FONCTION EQUITY
# ============================================================

def calculate_equity(current_date, current_prices):
    """
    Cash + valeur de marché des positions ouvertes.
    """

    equity = cash

    for ticker, position in positions.items():

        price = current_prices.get(
            ticker,
            position["Entry_Price"]
        )

        equity += (
            position["Shares"] * price
        )

    return equity


# ============================================================
# TRAITEMENT JOURNALIER
# ============================================================

dates = sorted(
    df["Date"].unique()
)

previous_prices = {}


for current_date in dates:

    day = df[
        df["Date"] == current_date
    ].copy()

    current_prices = {}

    for _, row in day.iterrows():

        ticker = row["Ticker"]

        current_prices[ticker] = row["Close"]


    # ========================================================
    # 1. GESTION DES POSITIONS EXISTANTES
    # ========================================================

    positions_to_close = []


    for ticker, position in list(
        positions.items()
    ):

        row_data = day[
            day["Ticker"] == ticker
        ]

        if row_data.empty:
            continue

        row = row_data.iloc[0]

        entry_price = position["Entry_Price"]

        stop_price = (
            entry_price
            * (1 - STOP_LOSS_PCT)
        )

        target_price = (
            entry_price
            * (1 + TAKE_PROFIT_PCT)
        )

        low = row["Low"]
        high = row["High"]

        exit_price = None
        exit_reason = None


        # ----------------------------------------------------
        # STOP LOSS
        # ----------------------------------------------------

        if low <= stop_price:

            exit_price = stop_price
            exit_reason = "SL"


        # ----------------------------------------------------
        # TAKE PROFIT
        # ----------------------------------------------------

        elif high >= target_price:

            exit_price = target_price
            exit_reason = "TP"


        # ----------------------------------------------------
        # TIME EXIT
        # ----------------------------------------------------

        else:

            holding_days = (
                current_date
                - position["Entry_Date"]
            ).days

            if holding_days >= MAX_HOLD_DAYS:

                exit_price = row["Close"]
                exit_reason = "TIME"


        # ----------------------------------------------------
        # FERMETURE
        # ----------------------------------------------------

        if exit_price is not None:

            shares = position["Shares"]

            proceeds = (
                shares * exit_price
            )

            cash += proceeds

            pnl = (
                exit_price
                - entry_price
            ) * shares

            pnl_pct = (
                exit_price
                / entry_price
                - 1
            )

            trades.append({
                "Ticker": ticker,
                "Entry_Date": position["Entry_Date"],
                "Exit_Date": current_date,

                "Entry_Price": entry_price,
                "Exit_Price": exit_price,

                "Shares": shares,

                "Position_Value": position[
                    "Position_Value"
                ],

                "PnL": pnl,
                "Return": pnl_pct,

                "Exit_Reason": exit_reason,

                "Hold_Days": (
                    current_date
                    - position["Entry_Date"]
                ).days,

                "ATR_Pct": position["ATR_Pct"],
                "Return_10D": position["Return_10D"],
            })

            positions_to_close.append(
                ticker
            )


    for ticker in positions_to_close:

        del positions[ticker]


    # ========================================================
    # 2. DETECTION DES NOUVEAUX SIGNAUX
    # ========================================================

    # On calcule les seuils à partir du TRAIN
    # correspondant à la période TEST.

    active_window = None

    for window in WINDOWS:

        (
            name,
            train_start,
            train_end,
            test_start,
            test_end,
        ) = window

        if (
            current_date >= pd.Timestamp(test_start)
            and
            current_date <= pd.Timestamp(test_end)
        ):

            active_window = window
            break


    if active_window is None:
        continue


    (
        window_name,
        train_start,
        train_end,
        test_start,
        test_end,
    ) = active_window


    train = df[
        (df["Date"] >= train_start)
        &
        (df["Date"] <= train_end)
    ]


    atr_threshold = train[
        "ATR_Pct"
    ].quantile(Q)

    return10_threshold = train[
        "Return_10D"
    ].quantile(Q)


    # ========================================================
    # 3. SIGNAUX
    # ========================================================

    signals = day[
        (day["ATR_Pct"] >= atr_threshold)
        &
        (day["Return_10D"] >= return10_threshold)
    ].copy()


    if signals.empty:
        continue


    # ========================================================
    # 4. ENTREE LE LENDEMAIN
    # ========================================================

    # Les signaux du jour T sont mémorisés.
    #
    # Pour garder le moteur simple et éviter tout look-ahead,
    # l'entrée sera effectuée au prochain Open.

    for _, signal in signals.iterrows():

        ticker = signal["Ticker"]

        if ticker in positions:
            continue

        if len(positions) >= MAX_POSITIONS:
            break

        # ----------------------------------------------------
        # Chercher la prochaine séance
        # ----------------------------------------------------

        future_rows = df[
            (df["Ticker"] == ticker)
            &
            (df["Date"] > current_date)
        ].sort_values("Date")

        if future_rows.empty:
            continue

        next_row = future_rows.iloc[0]

        next_date = next_row["Date"]

        # Si le prochain jour est hors de la fenêtre test,
        # on n'ouvre pas la position.
        if next_date > pd.Timestamp(test_end):
            continue

        entry_price = next_row["Open"]

        if pd.isna(entry_price) or entry_price <= 0:
            continue

        # ----------------------------------------------------
        # Taille de position
        # ----------------------------------------------------

        current_equity = calculate_equity(
            current_date,
            current_prices
        )

        position_value = (
            current_equity
            * POSITION_SIZE_PCT
        )

        # Impossible d'investir plus que le cash disponible.
        position_value = min(
            position_value,
            cash
        )

        if position_value <= 0:
            continue

        shares = (
            position_value
            / entry_price
        )

        if shares <= 0:
            continue

        # ----------------------------------------------------
        # RESERVE CASH
        # ----------------------------------------------------

        cash -= position_value

        # ----------------------------------------------------
        # CREATION POSITION
        # ----------------------------------------------------

        positions[ticker] = {
            "Ticker": ticker,
            "Entry_Date": next_date,
            "Entry_Price": entry_price,
            "Shares": shares,
            "Position_Value": position_value,
            "ATR_Pct": signal["ATR_Pct"],
            "Return_10D": signal["Return_10D"],
        }


# ============================================================
# LIQUIDATION FINALE
# ============================================================

if positions:

    last_date = dates[-1]

    last_day = df[
        df["Date"] == last_date
    ]

    for ticker, position in list(
        positions.items()
    ):

        row_data = last_day[
            last_day["Ticker"] == ticker
        ]

        if row_data.empty:
            continue

        row = row_data.iloc[0]

        exit_price = row["Close"]

        shares = position["Shares"]

        proceeds = (
            shares * exit_price
        )

        cash += proceeds

        pnl = (
            exit_price
            - position["Entry_Price"]
        ) * shares

        trades.append({
            "Ticker": ticker,
            "Entry_Date": position["Entry_Date"],
            "Exit_Date": last_date,

            "Entry_Price": position["Entry_Price"],
            "Exit_Price": exit_price,

            "Shares": shares,

            "Position_Value": position[
                "Position_Value"
            ],

            "PnL": pnl,

            "Return": (
                exit_price
                / position["Entry_Price"]
                - 1
            ),

            "Exit_Reason": "FINAL",
            "Hold_Days": (
                last_date
                - position["Entry_Date"]
            ).days,

            "ATR_Pct": position["ATR_Pct"],
            "Return_10D": position["Return_10D"],
        })


# ============================================================
# RESULTATS TRADES
# ============================================================

trades_df = pd.DataFrame(trades)

if trades_df.empty:

    print("\nAucun trade généré.")

else:

    TRADES_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    trades_df.to_csv(
        TRADES_FILE,
        index=False
    )

    print("\n" + "=" * 70)
    print("RESULTATS")
    print("=" * 70)

    total_trades = len(trades_df)

    winners = trades_df[
        trades_df["PnL"] > 0
    ]

    losers = trades_df[
        trades_df["PnL"] <= 0
    ]

    win_rate = (
        len(winners)
        / total_trades
    )

    total_pnl = trades_df["PnL"].sum()

    total_return = (
        total_pnl
        / INITIAL_CAPITAL
    )

    avg_trade = (
        trades_df["Return"].mean()
    )

    median_trade = (
        trades_df["Return"].median()
    )

    gross_profit = winners["PnL"].sum()

    gross_loss = abs(
        losers["PnL"].sum()
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    print(f"\nTrades        : {total_trades:,}")
    print(
        f"Gagnants      : {len(winners):,}"
    )
    print(
        f"Perdants      : {len(losers):,}"
    )
    print(
        f"Win rate      : {win_rate * 100:.2f}%"
    )
    print(
        f"PnL total     : ${total_pnl:,.2f}"
    )
    print(
        f"Return        : {total_return * 100:.2f}%"
    )
    print(
        f"Trade moyen   : {avg_trade * 100:.3f}%"
    )
    print(
        f"Trade médian  : {median_trade * 100:.3f}%"
    )
    print(
        f"Profit Factor : {profit_factor:.2f}"
    )

    print("\nSorties :")

    print(
        trades_df["Exit_Reason"]
        .value_counts()
        .to_string()
    )

    print("\nPar année :")

    trades_df["Exit_Year"] = pd.to_datetime(
        trades_df["Exit_Date"]
    ).dt.year

    yearly = trades_df.groupby(
        "Exit_Year"
    ).agg(
        Trades=("PnL", "count"),
        PnL=("PnL", "sum"),
        Avg_Return=("Return", "mean"),
        Win_Rate=(
            "PnL",
            lambda x: (x > 0).mean()
        ),
    )

    print(yearly.to_string())


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 70)
print("BACKTEST TERMINÉ")
print("=" * 70)

print(
    f"\nTrades sauvegardés : {TRADES_FILE}"
)