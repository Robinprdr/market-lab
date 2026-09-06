import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD",
    "GOOGL", "META", "NFLX", "DIS", "AMZN", "TSLA", "HD", "NKE",
    "MCD", "LOW", "JPM", "BAC", "GS", "MS", "V", "MA", "BLK",
    "UNH", "JNJ", "LLY", "MRK", "ABBV", "PFE", "CAT", "GE", "HON",
    "UPS", "BA", "XOM", "CVX", "COP", "WMT", "COST", "KO", "PEP",
    "PLD", "AMT", "NEE", "DUK"
]

MARKET_TICKER = "SPY"

START_DATE = "2018-01-01"
END_DATE = "2025-12-20"

INITIAL_CAPITAL = 10_000.0

# Signal
DROP_THRESHOLD = -0.02

# On exclut les chutes extrêmes > 4%
# car notre stratégie V1 actuelle a été construite
# sur la zone -2% à -4%.
MAX_SIGNAL_DROP = -0.04

# Gestion de position
SL_PCT = -0.02
TP_PCT = 0.04
MAX_HOLDING_DAYS = 5

# Allocation
ALLOCATION_PER_TRADE = 0.20
MAX_POSITIONS = 5

# Indicateurs
SMA20_PERIOD = 20
SMA50_PERIOD = 50
SMA200_PERIOD = 200
VOLUME_PERIOD = 20
ATR_PERIOD = 14

# Pour l'instant : pas de frais/slippage.
# On les ajoutera dans une prochaine étape.
SLIPPAGE_PCT = 0.0
COMMISSION_RATE = 0.0

OUTPUT_DIR = Path("results/mean_reversion")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# INDICATEURS
# ============================================================

def calculate_indicators(df):
    df = df.copy()

    required = ["Open", "High", "Low", "Close", "Volume"]

    for col in required:
        if col not in df.columns:
            raise ValueError(f"Colonne manquante : {col}")

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    # Rendements
    df["Return"] = df["Close"].pct_change()

    # Moyennes mobiles
    df["SMA20"] = df["Close"].rolling(SMA20_PERIOD).mean()
    df["SMA50"] = df["Close"].rolling(SMA50_PERIOD).mean()
    df["SMA200"] = df["Close"].rolling(SMA200_PERIOD).mean()

    # Volume
    df["Volume_Moyen_20"] = (
        df["Volume"]
        .rolling(VOLUME_PERIOD)
        .mean()
    )

    df["Volume_Ratio"] = (
        df["Volume"] / df["Volume_Moyen_20"]
    )

    # True Range
    previous_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - previous_close).abs()
    tr3 = (df["Low"] - previous_close).abs()

    df["True_Range"] = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    # ATR
    df["ATR"] = (
        df["True_Range"]
        .rolling(ATR_PERIOD)
        .mean()
    )

    df["ATR_Pct"] = (
        df["ATR"] / df["Close"]
    )

    # Distances aux SMA
    df["Distance_SMA20"] = (
        df["Close"] / df["SMA20"] - 1
    )

    df["Distance_SMA50"] = (
        df["Close"] / df["SMA50"] - 1
    )

    df["Distance_SMA200"] = (
        df["Close"] / df["SMA200"] - 1
    )

    # Ratio chute / volatilité
    df["Drop_ATR_Ratio"] = (
        df["Return"].abs() / df["ATR_Pct"]
    )

    # Momentum
    df["Return_3D"] = (
        df["Close"].pct_change(3)
    )

    df["Return_5D"] = (
        df["Close"].pct_change(5)
    )

    df["Return_10D"] = (
        df["Close"].pct_change(10)
    )

    # Nombre de jours rouges sur les 5 derniers jours
    df["Negative_Days_5"] = (
        (df["Return"] < 0)
        .rolling(5)
        .sum()
    )

    return df


# ============================================================
# SCORE
# ============================================================

def calculate_score(row, spy_row):
    score = 0

    # 1. Distance SMA20
    if (
        pd.notna(row["Distance_SMA20"])
        and 0 <= row["Distance_SMA20"] <= 0.10
    ):
        score += 1

    # 2. Distance SMA50
    if (
        pd.notna(row["Distance_SMA50"])
        and 0 <= row["Distance_SMA50"] <= 0.20
    ):
        score += 1

    # 3. Momentum 3 jours négatif
    if (
        pd.notna(row["Return_3D"])
        and row["Return_3D"] < 0
    ):
        score += 1

    # 4. Chute suffisamment importante
    # par rapport à la volatilité
    if (
        pd.notna(row["Drop_ATR_Ratio"])
        and row["Drop_ATR_Ratio"] >= 1
    ):
        score += 1

    # 5. Contexte SPY
    if (
        pd.notna(spy_row["Return"])
        and spy_row["Return"] > -0.02
    ):
        score += 1

    return score


# ============================================================
# TELECHARGEMENT
# ============================================================

def download_data():
    all_tickers = TICKERS + [MARKET_TICKER]

    print("=" * 70)
    print("TELECHARGEMENT DES DONNEES")
    print("=" * 70)

    print(f"Actions : {len(TICKERS)}")
    print(f"Marché  : {MARKET_TICKER}")
    print(f"Période : {START_DATE} -> {END_DATE}")
    print()

    data = yf.download(
        all_tickers,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True
    )

    if data.empty:
        raise RuntimeError(
            "Aucune donnée téléchargée."
        )

    return data


# ============================================================
# PREPARATION DES DONNEES
# ============================================================

def prepare_data(raw_data):
    prepared = {}

    for ticker in TICKERS + [MARKET_TICKER]:

        if ticker not in raw_data.columns.get_level_values(0):
            print(
                f"[WARNING] Données absentes : {ticker}"
            )
            continue

        df = raw_data[ticker].copy()

        if df.empty:
            continue

        df = calculate_indicators(df)

        prepared[ticker] = df

    if MARKET_TICKER not in prepared:
        raise RuntimeError(
            "SPY absent : impossible de construire le contexte marché."
        )

    return prepared


# ============================================================
# CONSTRUCTION DES SIGNAUX
# ============================================================

def build_signals(prepared):
    spy = prepared[MARKET_TICKER]

    signals = []

    for ticker in TICKERS:

        if ticker not in prepared:
            continue

        df = prepared[ticker]

        for i in range(len(df) - 1):

            signal_date = df.index[i]
            entry_date = df.index[i + 1]

            row = df.iloc[i]

            if signal_date not in spy.index:
                continue

            spy_row = spy.loc[signal_date]

            signal_drop = row["Return"]

            # Données nécessaires
            if pd.isna(signal_drop):
                continue

            if pd.isna(row["SMA50"]):
                continue

            if pd.isna(row["Volume_Moyen_20"]):
                continue

            # ------------------------------------------------
            # SIGNAL DE BASE
            # ------------------------------------------------

            base_signal = (
                signal_drop <= DROP_THRESHOLD
                and signal_drop >= MAX_SIGNAL_DROP
                and row["Close"] > row["SMA50"]
                and row["Volume"] > row["Volume_Moyen_20"]
            )

            if not base_signal:
                continue

            # ------------------------------------------------
            # SCORE
            # ------------------------------------------------

            score = calculate_score(
                row,
                spy_row
            )

            signals.append({
                "Ticker": ticker,
                "Signal_Date": signal_date,
                "Entry_Date": entry_date,

                "Signal_Close": row["Close"],
                "Signal_Drop": signal_drop,

                "Score": score,

                "Distance_SMA20": row["Distance_SMA20"],
                "Distance_SMA50": row["Distance_SMA50"],
                "Distance_SMA200": row["Distance_SMA200"],

                "Return_3D": row["Return_3D"],
                "Return_5D": row["Return_5D"],
                "Return_10D": row["Return_10D"],

                "ATR_Pct": row["ATR_Pct"],
                "Drop_ATR_Ratio": row["Drop_ATR_Ratio"],

                "Volume_Ratio": row["Volume_Ratio"],
                "Negative_Days_5": row["Negative_Days_5"],

                "SPY_Return": spy_row["Return"],
                "SPY_Distance_SMA50": spy_row["Distance_SMA50"],
                "SPY_Volume_Ratio": spy_row["Volume_Ratio"]
            })

    signals_df = pd.DataFrame(signals)

    if signals_df.empty:
        raise RuntimeError(
            "Aucun signal détecté."
        )

    signals_df = signals_df.sort_values(
        ["Entry_Date", "Score", "Ticker"],
        ascending=[True, False, True]
    ).reset_index(drop=True)

    return signals_df


# ============================================================
# UTILITAIRES PORTEFEUILLE
# ============================================================

def apply_buy_slippage(price):
    return price * (1 + SLIPPAGE_PCT)


def apply_sell_slippage(price):
    return price * (1 - SLIPPAGE_PCT)


def commission(value):
    return value * COMMISSION_RATE


def calculate_equity(
    cash,
    positions,
    prepared,
    current_date,
    last_close
):
    equity = cash

    for ticker, position in positions.items():

        if ticker in prepared:

            df = prepared[ticker]

            if current_date in df.index:
                price = df.loc[current_date, "Close"]
                last_close[ticker] = price

            else:
                price = last_close.get(
                    ticker,
                    position["entry_price"]
                )

        else:
            price = position["entry_price"]

        equity += (
            position["shares"] * price
        )

    return equity


# ============================================================
# FERMETURE D'UNE POSITION
# ============================================================

def close_position(
    ticker,
    position,
    exit_price,
    exit_date,
    reason,
    cash,
    trades
):
    exit_price = apply_sell_slippage(exit_price)

    gross_value = (
        position["shares"] * exit_price
    )

    fees = commission(gross_value)

    net_value = gross_value - fees

    cash += net_value

    pnl = (
        net_value
        - position["entry_cost"]
    )

    pnl_pct = (
        pnl / position["entry_cost"]
    )

    trade = {
        "Ticker": ticker,

        "Signal_Date": position["signal_date"],
        "Entry_Date": position["entry_date"],
        "Exit_Date": exit_date,

        "Entry_Price": position["entry_price"],
        "Exit_Price": exit_price,

        "Shares": position["shares"],

        "Entry_Value": position["entry_cost"],
        "Exit_Value": net_value,

        "PnL": pnl,
        "PnL_Pct": pnl_pct,

        "Score": position["score"],

        "Signal_Drop": position["signal_drop"],

        "Exit_Reason": reason,

        "Holding_Days": position["holding_days"],

        "Distance_SMA20": position["Distance_SMA20"],
        "Distance_SMA50": position["Distance_SMA50"],
        "Distance_SMA200": position["Distance_SMA200"],

        "Return_3D": position["Return_3D"],
        "Return_5D": position["Return_5D"],
        "Return_10D": position["Return_10D"],

        "ATR_Pct": position["ATR_Pct"],
        "Drop_ATR_Ratio": position["Drop_ATR_Ratio"],

        "Volume_Ratio": position["Volume_Ratio"],
        "Negative_Days_5": position["Negative_Days_5"],

        "SPY_Return": position["SPY_Return"],
        "SPY_Distance_SMA50": position["SPY_Distance_SMA50"],
        "SPY_Volume_Ratio": position["SPY_Volume_Ratio"]
    }

    trades.append(trade)

    return cash


# ============================================================
# BACKTEST PORTEFEUILLE
# ============================================================

def run_portfolio_backtest(
    prepared,
    signals,
    strategy_name,
    min_score
):
    print()
    print("=" * 70)
    print(f"BACKTEST : {strategy_name}")
    print("=" * 70)

    # --------------------------------------------------------
    # Sélection des signaux
    # --------------------------------------------------------

    if strategy_name == "BASE":
        selected = signals.copy()

    elif strategy_name == "SCORE4":
        selected = signals[
            signals["Score"] >= 4
        ].copy()

    elif strategy_name == "SCORE5":
        selected = signals[
            signals["Score"] >= 5
        ].copy()

    else:
        selected = signals[
            signals["Score"] >= min_score
        ].copy()

    selected = selected.sort_values(
        ["Entry_Date", "Score", "Ticker"],
        ascending=[True, False, True]
    ).reset_index(drop=True)

    if selected.empty:
        print("Aucun signal.")
        return None, None

    # --------------------------------------------------------
    # Index des signaux par date
    # --------------------------------------------------------

    signals_by_date = {}

    for _, signal in selected.iterrows():

        date = signal["Entry_Date"]

        if date not in signals_by_date:
            signals_by_date[date] = []

        signals_by_date[date].append(signal)

    # --------------------------------------------------------
    # Calendrier marché
    # --------------------------------------------------------

    market_dates = prepared[
        MARKET_TICKER
    ].index

    # --------------------------------------------------------
    # Variables portefeuille
    # --------------------------------------------------------

    cash = INITIAL_CAPITAL

    positions = {}

    trades = []

    equity_history = []

    last_close = {}

    # --------------------------------------------------------
    # Boucle temporelle
    # --------------------------------------------------------

    for current_date in market_dates:

        # ====================================================
        # 1. GESTION DES POSITIONS EXISTANTES A L'OPEN
        # ====================================================

        for ticker in list(positions.keys()):

            position = positions[ticker]

            if ticker not in prepared:
                continue

            df = prepared[ticker]

            if current_date not in df.index:
                continue

            row = df.loc[current_date]

            open_price = row["Open"]

            stop_price = (
                position["entry_price"]
                * (1 + SL_PCT)
            )

            target_price = (
                position["entry_price"]
                * (1 + TP_PCT)
            )

            # Gap sous le stop
            if open_price <= stop_price:

                cash = close_position(
                    ticker,
                    position,
                    open_price,
                    current_date,
                    "SL_GAP",
                    cash,
                    trades
                )

                del positions[ticker]

                continue

            # Gap au-dessus du target
            if open_price >= target_price:

                cash = close_position(
                    ticker,
                    position,
                    open_price,
                    current_date,
                    "TP_GAP",
                    cash,
                    trades
                )

                del positions[ticker]

                continue

        # ====================================================
        # 2. ENTREES A L'OPEN
        # ====================================================

        candidates = signals_by_date.get(
            current_date,
            []
        )

        for signal in candidates:

            if len(positions) >= MAX_POSITIONS:
                break

            ticker = signal["Ticker"]

            # Une seule position par action
            if ticker in positions:
                continue

            if ticker not in prepared:
                continue

            df = prepared[ticker]

            if current_date not in df.index:
                continue

            row = df.loc[current_date]

            open_price = row["Open"]

            if pd.isna(open_price) or open_price <= 0:
                continue

            # -----------------------------------------------
            # Valeur actuelle du portefeuille
            # -----------------------------------------------

            equity = calculate_equity(
                cash,
                positions,
                prepared,
                current_date,
                last_close
            )

            allocation_value = (
                equity
                * ALLOCATION_PER_TRADE
            )

            # On ne peut pas investir plus que le cash
            position_value = min(
                allocation_value,
                cash
            )

            if position_value <= 0:
                continue

            entry_price = apply_buy_slippage(
                open_price
            )

            # Frais d'entrée
            entry_fees = commission(
                position_value
            )

            available_for_shares = (
                position_value - entry_fees
            )

            shares = (
                available_for_shares
                / entry_price
            )

            if shares <= 0:
                continue

            entry_cost = (
                shares * entry_price
                + entry_fees
            )

            if entry_cost > cash:
                continue

            cash -= entry_cost

            positions[ticker] = {
                "signal_date": signal["Signal_Date"],
                "entry_date": current_date,

                "entry_price": entry_price,
                "entry_cost": entry_cost,

                "shares": shares,

                "score": signal["Score"],
                "signal_drop": signal["Signal_Drop"],

                "holding_days": 0,

                "Distance_SMA20":
                    signal["Distance_SMA20"],

                "Distance_SMA50":
                    signal["Distance_SMA50"],

                "Distance_SMA200":
                    signal["Distance_SMA200"],

                "Return_3D":
                    signal["Return_3D"],

                "Return_5D":
                    signal["Return_5D"],

                "Return_10D":
                    signal["Return_10D"],

                "ATR_Pct":
                    signal["ATR_Pct"],

                "Drop_ATR_Ratio":
                    signal["Drop_ATR_Ratio"],

                "Volume_Ratio":
                    signal["Volume_Ratio"],

                "Negative_Days_5":
                    signal["Negative_Days_5"],

                "SPY_Return":
                    signal["SPY_Return"],

                "SPY_Distance_SMA50":
                    signal["SPY_Distance_SMA50"],

                "SPY_Volume_Ratio":
                    signal["SPY_Volume_Ratio"]
            }

        # ====================================================
        # 3. GESTION INTRADAY
        # ====================================================

        for ticker in list(positions.keys()):

            position = positions[ticker]

            if ticker not in prepared:
                continue

            df = prepared[ticker]

            if current_date not in df.index:
                continue

            row = df.loc[current_date]

            high = row["High"]
            low = row["Low"]
            close = row["Close"]

            stop_price = (
                position["entry_price"]
                * (1 + SL_PCT)
            )

            target_price = (
                position["entry_price"]
                * (1 + TP_PCT)
            )

            # ------------------------------------------------
            # SL + TP touchés le même jour
            # ------------------------------------------------
            # Hypothèse conservatrice :
            # SL en premier.
            # ------------------------------------------------

            if low <= stop_price:

                cash = close_position(
                    ticker,
                    position,
                    stop_price,
                    current_date,
                    "SL",
                    cash,
                    trades
                )

                del positions[ticker]

                continue

            if high >= target_price:

                cash = close_position(
                    ticker,
                    position,
                    target_price,
                    current_date,
                    "TP",
                    cash,
                    trades
                )

                del positions[ticker]

                continue

            # ------------------------------------------------
            # TIME EXIT
            # ------------------------------------------------

            if position["entry_date"] != current_date:

                position["holding_days"] += 1

            if (
                position["holding_days"]
                >= MAX_HOLDING_DAYS
            ):

                cash = close_position(
                    ticker,
                    position,
                    close,
                    current_date,
                    "TIME",
                    cash,
                    trades
                )

                del positions[ticker]

                continue

            # Sauvegarde du dernier close connu
            last_close[ticker] = close

        # ====================================================
        # 4. EQUITY DE FIN DE JOURNEE
        # ====================================================

        equity = calculate_equity(
            cash,
            positions,
            prepared,
            current_date,
            last_close
        )

        equity_history.append({
            "Date": current_date,
            "Cash": cash,
            "Open_Positions": len(positions),
            "Equity": equity
        })

    # ========================================================
    # 5. LIQUIDATION FINALE
    # ========================================================

    final_date = market_dates[-1]

    for ticker in list(positions.keys()):

        position = positions[ticker]

        if ticker in prepared:

            df = prepared[ticker]

            if final_date in df.index:
                final_price = df.loc[
                    final_date,
                    "Close"
                ]
            else:
                final_price = last_close.get(
                    ticker,
                    position["entry_price"]
                )

        else:
            final_price = position["entry_price"]

        cash = close_position(
            ticker,
            position,
            final_price,
            final_date,
            "FINAL",
            cash,
            trades
        )

        del positions[ticker]

    # Mise à jour de la dernière equity
    if equity_history:

        equity_history[-1]["Cash"] = cash
        equity_history[-1]["Open_Positions"] = 0
        equity_history[-1]["Equity"] = cash

    # ========================================================
    # DATAFRAMES
    # ========================================================

    trades_df = pd.DataFrame(trades)

    equity_df = pd.DataFrame(
        equity_history
    )

    # ========================================================
    # METRIQUES
    # ========================================================

    if equity_df.empty:
        return None, None

    final_capital = float(
        equity_df["Equity"].iloc[-1]
    )

    total_return = (
        final_capital
        / INITIAL_CAPITAL
        - 1
    )

    # CAGR
    start_date = equity_df["Date"].iloc[0]
    end_date = equity_df["Date"].iloc[-1]

    years = (
        end_date - start_date
    ).days / 365.25

    if years > 0:
        cagr = (
            final_capital
            / INITIAL_CAPITAL
        ) ** (1 / years) - 1
    else:
        cagr = np.nan

    # --------------------------------------------------------
    # Drawdown
    # --------------------------------------------------------

    equity_df["Peak"] = (
        equity_df["Equity"]
        .cummax()
    )

    equity_df["Drawdown"] = (
        equity_df["Equity"]
        / equity_df["Peak"]
        - 1
    )

    max_drawdown = equity_df[
        "Drawdown"
    ].min()

    # --------------------------------------------------------
    # Trade metrics
    # --------------------------------------------------------

    if not trades_df.empty:

        wins = trades_df[
            trades_df["PnL"] > 0
        ]

        losses = trades_df[
            trades_df["PnL"] < 0
        ]

        win_rate = (
            len(wins)
            / len(trades_df)
        )

        avg_pnl = (
            trades_df["PnL"].mean()
        )

        median_pnl_pct = (
            trades_df["PnL_Pct"].median()
        )

        gross_profit = wins["PnL"].sum()
        gross_loss = abs(
            losses["PnL"].sum()
        )

        if gross_loss > 0:
            profit_factor = (
                gross_profit
                / gross_loss
            )
        else:
            profit_factor = np.inf

        expectancy = avg_pnl

    else:

        win_rate = np.nan
        avg_pnl = np.nan
        median_pnl_pct = np.nan
        profit_factor = np.nan
        expectancy = np.nan

    # --------------------------------------------------------
    # Sharpe basé sur les rendements quotidiens
    # --------------------------------------------------------

    daily_returns = (
        equity_df["Equity"]
        .pct_change()
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
        sharpe = np.nan

    # --------------------------------------------------------
    # Benchmark SPY
    # --------------------------------------------------------

    spy = prepared[MARKET_TICKER]

    spy_valid = spy.loc[
        (spy.index >= start_date)
        & (spy.index <= end_date)
    ]

    if len(spy_valid) >= 2:

        spy_start = spy_valid["Close"].iloc[0]
        spy_end = spy_valid["Close"].iloc[-1]

        spy_return = (
            spy_end
            / spy_start
            - 1
        )

    else:
        spy_return = np.nan

    metrics = {
        "Strategy": strategy_name,

        "Initial_Capital":
            INITIAL_CAPITAL,

        "Final_Capital":
            final_capital,

        "Total_Return":
            total_return,

        "CAGR":
            cagr,

        "Max_Drawdown":
            max_drawdown,

        "Sharpe":
            sharpe,

        "Trades":
            len(trades_df),

        "Win_Rate":
            win_rate,

        "Avg_PnL":
            avg_pnl,

        "Median_PnL_Pct":
            median_pnl_pct,

        "Profit_Factor":
            profit_factor,

        "Expectancy":
            expectancy,

        "SPY_BuyHold":
            spy_return
    }

    metrics_df = pd.DataFrame([metrics])

    return (
        metrics_df,
        trades_df,
        equity_df
    )


# ============================================================
# RAPPORT
# ============================================================

def print_report(
    metrics_df,
    trades_df,
    equity_df
):
    if metrics_df is None:
        return

    m = metrics_df.iloc[0]

    print()
    print("-" * 70)
    print("RESULTATS")
    print("-" * 70)

    print(
        f"Capital initial : "
        f"${m['Initial_Capital']:,.2f}"
    )

    print(
        f"Capital final   : "
        f"${m['Final_Capital']:,.2f}"
    )

    print(
        f"Performance     : "
        f"{m['Total_Return'] * 100:.2f}%"
    )

    print(
        f"CAGR            : "
        f"{m['CAGR'] * 100:.2f}%"
    )

    print(
        f"Max Drawdown    : "
        f"{m['Max_Drawdown'] * 100:.2f}%"
    )

    print(
        f"Sharpe          : "
        f"{m['Sharpe']:.2f}"
    )

    print(
        f"Trades          : "
        f"{int(m['Trades'])}"
    )

    print(
        f"Win Rate        : "
        f"{m['Win_Rate'] * 100:.2f}%"
    )

    print(
        f"Profit Factor   : "
        f"{m['Profit_Factor']:.2f}"
    )

    print(
        f"Expectancy      : "
        f"${m['Expectancy']:.2f}"
    )

    print(
        f"SPY Buy & Hold  : "
        f"{m['SPY_BuyHold'] * 100:.2f}%"
    )

    if not trades_df.empty:

        print()
        print("SORTIES :")

        exits = (
            trades_df["Exit_Reason"]
            .value_counts()
        )

        for reason, count in exits.items():
            print(
                f"  {reason:<10} : {count}"
            )

        print()
        print("PERFORMANCE PAR SCORE :")

        score_stats = (
            trades_df
            .groupby("Score")
            .agg(
                Trades=("PnL", "count"),
                Win_Rate=(
                    "PnL",
                    lambda x:
                    (x > 0).mean()
                ),
                Avg_PnL=("PnL_Pct", "mean"),
                Total_PnL=("PnL_Pct", "sum")
            )
            .reset_index()
        )

        for _, row in score_stats.iterrows():

            print(
                f"  Score {int(row['Score'])} "
                f"| trades={int(row['Trades'])} "
                f"| win={row['Win_Rate'] * 100:.1f}% "
                f"| avg={row['Avg_PnL'] * 100:.3f}% "
                f"| total={row['Total_PnL'] * 100:.2f}%"
            )


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    print()
    print("=" * 70)
    print("BACKTEST V4")
    print("PORTFOLIO GLOBAL - 47 ACTIONS")
    print("=" * 70)

    # --------------------------------------------------------
    # 1. Téléchargement
    # --------------------------------------------------------

    raw_data = download_data()

    # --------------------------------------------------------
    # 2. Préparation
    # --------------------------------------------------------

    print()
    print("Calcul des indicateurs...")

    prepared = prepare_data(
        raw_data
    )

    print(
        f"Données préparées : "
        f"{len(prepared)} tickers"
    )

    # --------------------------------------------------------
    # 3. Signaux
    # --------------------------------------------------------

    print()
    print("Construction des signaux...")

    signals = build_signals(
        prepared
    )

    print(
        f"Signaux de base : "
        f"{len(signals)}"
    )

    print()
    print("Distribution des scores :")

    score_distribution = (
        signals["Score"]
        .value_counts()
        .sort_index()
    )

    for score, count in score_distribution.items():

        pct = (
            count
            / len(signals)
            * 100
        )

        print(
            f"  Score {score} : "
            f"{count} ({pct:.1f}%)"
        )

    # --------------------------------------------------------
    # Sauvegarde des signaux
    # --------------------------------------------------------

    signals.to_csv(
        OUTPUT_DIR
        / "backtest_v4_signals.csv",
        index=False
    )

    # --------------------------------------------------------
    # 4. Trois stratégies
    # --------------------------------------------------------

    strategies = [
        ("BASE", 0),
        ("SCORE4", 4),
        ("SCORE5", 5)
    ]

    all_metrics = []

    for strategy_name, min_score in strategies:

        result = run_portfolio_backtest(
            prepared,
            signals,
            strategy_name,
            min_score
        )

        if result is None:
            continue

        metrics_df, trades_df, equity_df = result

        print_report(
            metrics_df,
            trades_df,
            equity_df
        )

        all_metrics.append(
            metrics_df
        )

        # ----------------------------------------------------
        # Sauvegardes
        # ----------------------------------------------------

        trades_df.to_csv(
            OUTPUT_DIR
            / f"backtest_v4_{strategy_name.lower()}_trades.csv",
            index=False
        )

        equity_df.to_csv(
            OUTPUT_DIR
            / f"backtest_v4_{strategy_name.lower()}_equity.csv",
            index=False
        )

        metrics_df.to_csv(
            OUTPUT_DIR
            / f"backtest_v4_{strategy_name.lower()}_metrics.csv",
            index=False
        )

    # --------------------------------------------------------
    # 5. Résumé global
    # --------------------------------------------------------

    if all_metrics:

        summary = pd.concat(
            all_metrics,
            ignore_index=True
        )

        summary.to_csv(
            OUTPUT_DIR
            / "backtest_v4_summary.csv",
            index=False
        )

        print()
        print("=" * 70)
        print("COMPARAISON FINALE")
        print("=" * 70)

        for _, row in summary.iterrows():

            print()
            print(
                f"{row['Strategy']}"
            )

            print(
                f"  Capital final : "
                f"${row['Final_Capital']:,.2f}"
            )

            print(
                f"  Return        : "
                f"{row['Total_Return'] * 100:.2f}%"
            )

            print(
                f"  CAGR          : "
                f"{row['CAGR'] * 100:.2f}%"
            )

            print(
                f"  Drawdown      : "
                f"{row['Max_Drawdown'] * 100:.2f}%"
            )

            print(
                f"  Trades        : "
                f"{int(row['Trades'])}"
            )

            print(
                f"  Win Rate      : "
                f"{row['Win_Rate'] * 100:.2f}%"
            )

            print(
                f"  Profit Factor : "
                f"{row['Profit_Factor']:.2f}"
            )

            print(
                f"  Sharpe        : "
                f"{row['Sharpe']:.2f}"
            )

        print()
        print("=" * 70)
        print("FICHIERS CREES")
        print("=" * 70)

        print("backtest_v4_signals.csv")
        print("backtest_v4_base_trades.csv")
        print("backtest_v4_base_equity.csv")
        print("backtest_v4_base_metrics.csv")
        print("backtest_v4_score4_trades.csv")
        print("backtest_v4_score4_equity.csv")
        print("backtest_v4_score4_metrics.csv")
        print("backtest_v4_score5_trades.csv")
        print("backtest_v4_score5_equity.csv")
        print("backtest_v4_score5_metrics.csv")
        print("backtest_v4_summary.csv")

    print()
    print("=" * 70)
    print("BACKTEST V4 TERMINE")
    print("=" * 70)


if __name__ == "__main__":
    main()