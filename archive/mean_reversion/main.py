import yfinance as yf
import pandas as pd
import numpy as np


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

# On repart suffisamment loin pour conserver les périodes
# nécessaires à nos tests walk-forward.
START_DATE = "2018-01-01"

# On garde volontairement la même fin historique que notre
# précédent jeu de données pour pouvoir comparer les résultats.
END_DATE = "2025-12-20"

INITIAL_CAPITAL = 10000

# Signal principal :
# grosse baisse sur la journée précédente
DROP_THRESHOLD = -0.02

# Gestion de position
SL_PCT = -0.02
TP_PCT = 0.04
MAX_HOLDING_DAYS = 5

# Taille d'une position
ALLOCATION_PER_TRADE = 0.20

# Nombre maximum de positions simultanées
MAX_POSITIONS = 5

# Indicateurs
SMA20_PERIOD = 20
SMA50_PERIOD = 50
SMA200_PERIOD = 200
VOLUME_PERIOD = 20
ATR_PERIOD = 14


# ============================================================
# TELECHARGEMENT DES DONNEES
# ============================================================

print()
print("=" * 70)
print("TELECHARGEMENT DES DONNEES")
print("=" * 70)
print()

ALL_TICKERS = TICKERS + [MARKET_TICKER]

data = yf.download(
    ALL_TICKERS,
    start=START_DATE,
    end=END_DATE,
    auto_adjust=True,
    progress=False,
    group_by="ticker",
    threads=True
)

print(f"Actions demandées : {len(TICKERS)}")
print(f"Marché de référence : {MARKET_TICKER}")
print()


# ============================================================
# CALCUL DES INDICATEURS
# ============================================================

def calculate_indicators(df):
    """
    Calcule tous les indicateurs nécessaires
    pour les actions et pour SPY.
    """

    df = df.copy()

    # Sécurité : colonnes numériques
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    # Rendement journalier
    df["Return"] = df["Close"].pct_change()

    # Moyennes mobiles
    df["SMA20"] = df["Close"].rolling(SMA20_PERIOD).mean()
    df["SMA50"] = df["Close"].rolling(SMA50_PERIOD).mean()
    df["SMA200"] = df["Close"].rolling(SMA200_PERIOD).mean()

    # Volume moyen
    df["Volume_Moyen_20"] = (
        df["Volume"]
        .rolling(VOLUME_PERIOD)
        .mean()
    )

    # Ratio de volume
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

    # ATR en pourcentage du prix
    df["ATR_Pct"] = (
        df["ATR"] / df["Close"]
    )

    # Distance par rapport aux moyennes mobiles
    df["Distance_SMA20"] = (
        df["Close"] / df["SMA20"] - 1
    )

    df["Distance_SMA50"] = (
        df["Close"] / df["SMA50"] - 1
    )

    df["Distance_SMA200"] = (
        df["Close"] / df["SMA200"] - 1
    )

    # Rapport entre la baisse et l'ATR
    df["Drop_ATR_Ratio"] = (
        df["Return"].abs() / df["ATR_Pct"]
    )

    # Rendements sur plusieurs jours
    df["Return_3D"] = (
        df["Close"] / df["Close"].shift(3) - 1
    )

    df["Return_5D"] = (
        df["Close"] / df["Close"].shift(5) - 1
    )

    df["Return_10D"] = (
        df["Close"] / df["Close"].shift(10) - 1
    )

    # Nombre de journées négatives sur les 5 dernières séances
    negative_day = (df["Return"] < 0).astype(float)

    df["Negative_Days_5"] = (
        negative_day
        .rolling(5)
        .sum()
    )

    return df


# ============================================================
# PREPARATION DE SPY
# ============================================================

print("Préparation des données SPY...")

try:
    spy_data = data[MARKET_TICKER].copy()
except Exception:
    spy_data = None


if spy_data is None or spy_data.empty:
    print()
    print("ERREUR : impossible de récupérer les données SPY.")
    print()
    raise SystemExit


spy_data = calculate_indicators(spy_data)

print("SPY prêt.")
print()


# ============================================================
# VALIDATION DES UNITES
# ============================================================

def validate_decimal_units(df):
    """
    Vérifie que les indicateurs exprimés en pourcentage
    sont bien stockés sous forme décimale.

    Exemple :
    -2% = -0.02
    +4% = +0.04
    """

    columns_to_check = [
        "Return",
        "ATR_Pct",
        "Distance_SMA20",
        "Distance_SMA50",
        "Distance_SMA200"
    ]

    for column in columns_to_check:
        if column not in df.columns:
            continue

        values = df[column].dropna()

        if values.empty:
            continue

        max_abs = values.abs().max()

        if max_abs > 10:
            raise ValueError(
                f"Valeurs suspectes dans {column}: "
                f"maximum absolu = {max_abs}"
            )


# ============================================================
# TAILLE DE POSITION
# ============================================================

def calculate_position_size():
    """
    Version volontairement simple pour le laboratoire.

    Chaque position représente 20% du capital initial.

    Nous passerons plus tard à un sizing basé sur :
    capital × risque par trade / distance du stop.
    """

    return INITIAL_CAPITAL * ALLOCATION_PER_TRADE


# ============================================================
# BACKTEST D'UNE ACTION
# ============================================================

def backtest_stock(ticker, df):

    df = calculate_indicators(df)

    validate_decimal_units(df)

    trades = []

    cash = INITIAL_CAPITAL

    open_positions = []

    equity_curve = []

    # On commence assez loin pour avoir SMA200 + ATR
    start_index = max(
        SMA200_PERIOD,
        ATR_PERIOD,
        VOLUME_PERIOD
    )

    for i in range(start_index, len(df)):

        row = df.iloc[i]
        date = df.index[i]

        # ====================================================
        # 1. GESTION DES POSITIONS EXISTANTES
        # ====================================================

        remaining_positions = []

        for position in open_positions:

            entry_price = position["entry_price"]
            shares = position["shares"]
            entry_index = position["entry_index"]

            days_held = i - entry_index

            stop_price = entry_price * (1 + SL_PCT)
            target_price = entry_price * (1 + TP_PCT)

            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])

            exit_price = None
            exit_reason = None

            # ------------------------------------------------
            # SL et TP touchés le même jour
            # ------------------------------------------------

            stop_hit = low_price <= stop_price
            target_hit = high_price >= target_price

            if stop_hit and target_hit:

                # Hypothèse conservatrice :
                # le stop est considéré touché en premier.
                exit_price = stop_price
                exit_reason = "SL"

            elif stop_hit:

                exit_price = stop_price
                exit_reason = "SL"

            elif target_hit:

                exit_price = target_price
                exit_reason = "TP"

            elif days_held >= MAX_HOLDING_DAYS:

                exit_price = close_price
                exit_reason = "TIME"

            # ------------------------------------------------
            # POSITION FERMEE
            # ------------------------------------------------

            if exit_price is not None:

                pnl_pct = (
                    exit_price / entry_price - 1
                )

                pnl_dollars = (
                    shares
                    * entry_price
                    * pnl_pct
                )

                cash += shares * exit_price

                trades.append({
                    "Ticker": ticker,

                    # Date du signal
                    "Date": position["signal_date"],

                    "Entry_Date": position["entry_date"],
                    "Exit_Date": date,

                    "Signal_Drop": position["signal_drop"],
                    "ATR_Pct": position["atr_pct"],
                    "Drop_ATR_Ratio": position["drop_atr_ratio"],
                    "Volume_Ratio": position["volume_ratio"],

                    "Distance_SMA20": position["distance_sma20"],
                    "Distance_SMA50": position["distance_sma50"],
                    "Distance_SMA200": position["distance_sma200"],

                    "Return_3D": position["return_3d"],
                    "Return_5D": position["return_5d"],
                    "Return_10D": position["return_10d"],

                    "Negative_Days_5": position["negative_days_5"],

                    # Contexte SPY au moment du signal
                    "SPY_Return": position["spy_return"],
                    "SPY_Distance_SMA50": position["spy_distance_sma50"],
                    "SPY_Volume_Ratio": position["spy_volume_ratio"],

                    "Entry_Price": entry_price,
                    "Exit_Price": exit_price,

                    "PnL_Pct": pnl_pct,
                    "PnL_Dollars": pnl_dollars,

                    "Holding_Days": days_held,
                    "Days_Held": days_held,

                    "Exit": exit_reason,
                    "Exit_Reason": exit_reason
                })

            else:
                remaining_positions.append(position)

        open_positions = remaining_positions

        # ====================================================
        # 2. DETECTION D'UN NOUVEAU SIGNAL
        # ====================================================

        if i + 1 >= len(df):
            continue

        signal_drop = row["Return"]
        atr_pct = row["ATR_Pct"]
        drop_atr_ratio = row["Drop_ATR_Ratio"]
        volume_ratio = row["Volume_Ratio"]

        distance_sma20 = row["Distance_SMA20"]
        distance_sma50 = row["Distance_SMA50"]
        distance_sma200 = row["Distance_SMA200"]

        return_3d = row["Return_3D"]
        return_5d = row["Return_5D"]
        return_10d = row["Return_10D"]

        negative_days_5 = row["Negative_Days_5"]

        # ====================================================
        # DONNEES SPY DU MEME JOUR
        # ====================================================

        try:
            spy_row = spy_data.loc[date]

            spy_return = spy_row["Return"]
            spy_distance_sma50 = spy_row["Distance_SMA50"]
            spy_volume_ratio = spy_row["Volume_Ratio"]

        except KeyError:

            spy_return = np.nan
            spy_distance_sma50 = np.nan
            spy_volume_ratio = np.nan

        # ====================================================
        # CONDITIONS DE VALIDITE
        # ====================================================

        valid_indicators = all([
            pd.notna(signal_drop),
            pd.notna(atr_pct),
            pd.notna(drop_atr_ratio),
            pd.notna(volume_ratio),
            pd.notna(distance_sma20),
            pd.notna(distance_sma50),
            pd.notna(distance_sma200),
            pd.notna(return_3d),
            pd.notna(return_5d),
            pd.notna(return_10d),
            pd.notna(negative_days_5)
        ])

        if not valid_indicators:
            continue

        # ====================================================
        # STRATEGIE ACTUELLE
        # ====================================================

        signal = (
            signal_drop <= DROP_THRESHOLD
            and row["Close"] > row["SMA50"]
            and row["Volume"] > row["Volume_Moyen_20"]
        )

        if not signal:
            continue

        # Nombre maximum de positions
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ====================================================
        # ENTREE LE LENDEMAIN A L'OUVERTURE
        # ====================================================

        next_row = df.iloc[i + 1]

        entry_date = df.index[i + 1]
        entry_price = float(next_row["Open"])

        if not np.isfinite(entry_price) or entry_price <= 0:
            continue

        # Taille fixe provisoire
        position_value = min(
            calculate_position_size(),
            cash
        )

        if position_value <= 0:
            continue

        shares = position_value / entry_price

        cash -= position_value

        # ====================================================
        # CREATION DE LA POSITION
        # ====================================================

        position = {

            "entry_index": i + 1,
            "signal_date": date,
            "entry_date": entry_date,

            "entry_price": entry_price,
            "shares": shares,

            "signal_drop": float(signal_drop),
            "atr_pct": float(atr_pct),
            "drop_atr_ratio": float(drop_atr_ratio),
            "volume_ratio": float(volume_ratio),

            "distance_sma20": float(distance_sma20),
            "distance_sma50": float(distance_sma50),
            "distance_sma200": float(distance_sma200),

            "return_3d": float(return_3d),
            "return_5d": float(return_5d),
            "return_10d": float(return_10d),

            "negative_days_5": float(negative_days_5),

            "spy_return": (
                float(spy_return)
                if pd.notna(spy_return)
                else np.nan
            ),

            "spy_distance_sma50": (
                float(spy_distance_sma50)
                if pd.notna(spy_distance_sma50)
                else np.nan
            ),

            "spy_volume_ratio": (
                float(spy_volume_ratio)
                if pd.notna(spy_volume_ratio)
                else np.nan
            )
        }

        open_positions.append(position)

        # ====================================================
        # EQUITY
        # ====================================================

        market_value = 0

        for position in open_positions:

            market_value += (
                position["shares"]
                * float(row["Close"])
            )

        equity = cash + market_value

        equity_curve.append({
            "Date": date,
            "Equity": equity
        })

    # ========================================================
    # FERMETURE DES POSITIONS RESTANTES
    # ========================================================

    if len(df) > 0:

        final_date = df.index[-1]
        final_close = float(df.iloc[-1]["Close"])

        for position in open_positions:

            entry_price = position["entry_price"]
            shares = position["shares"]

            exit_price = final_close

            pnl_pct = (
                exit_price / entry_price - 1
            )

            pnl_dollars = (
                shares
                * entry_price
                * pnl_pct
            )

            cash += shares * exit_price

            days_held = (
                len(df) - 1
                - position["entry_index"]
            )

            trades.append({
                "Ticker": ticker,

                "Date": position["signal_date"],

                "Entry_Date": position["entry_date"],
                "Exit_Date": final_date,

                "Signal_Drop": position["signal_drop"],
                "ATR_Pct": position["atr_pct"],
                "Drop_ATR_Ratio": position["drop_atr_ratio"],
                "Volume_Ratio": position["volume_ratio"],

                "Distance_SMA20": position["distance_sma20"],
                "Distance_SMA50": position["distance_sma50"],
                "Distance_SMA200": position["distance_sma200"],

                "Return_3D": position["return_3d"],
                "Return_5D": position["return_5d"],
                "Return_10D": position["return_10d"],

                "Negative_Days_5": position["negative_days_5"],

                "SPY_Return": position["spy_return"],
                "SPY_Distance_SMA50": position["spy_distance_sma50"],
                "SPY_Volume_Ratio": position["spy_volume_ratio"],

                "Entry_Price": entry_price,
                "Exit_Price": exit_price,

                "PnL_Pct": pnl_pct,
                "PnL_Dollars": pnl_dollars,

                "Holding_Days": days_held,
                "Days_Held": days_held,

                "Exit": "FINAL",
                "Exit_Reason": "FINAL"
            })

    # ========================================================
    # RESULTATS
    # ========================================================

    final_capital = cash

    strategy_return = (
        final_capital / INITIAL_CAPITAL - 1
    )

    # Buy & Hold
    first_close = float(df.iloc[start_index]["Close"])
    last_close = float(df.iloc[-1]["Close"])

    buy_hold_return = (
        last_close / first_close - 1
    )

    # Drawdown
    if equity_curve:

        equity_df = pd.DataFrame(equity_curve)

        equity_df["Peak"] = (
            equity_df["Equity"]
            .cummax()
        )

        equity_df["Drawdown"] = (
            equity_df["Equity"]
            / equity_df["Peak"]
            - 1
        )

        max_drawdown = equity_df["Drawdown"].min()

    else:

        max_drawdown = 0

    return (
        final_capital,
        strategy_return,
        buy_hold_return,
        max_drawdown,
        trades
    )


# ============================================================
# BACKTEST GLOBAL
# ============================================================

print("=" * 70)
print("LANCEMENT DU BACKTEST")
print("=" * 70)
print()

all_trades = []
results = []


for index, ticker in enumerate(TICKERS, start=1):

    print(
        f"[{index:02d}/{len(TICKERS)}] "
        f"Analyse de {ticker}..."
    )

    try:

        stock_data = data[ticker].copy()

        if stock_data.empty:
            print(f"  -> aucune donnée")
            continue

        (
            final_capital,
            strategy_return,
            buy_hold_return,
            max_drawdown,
            trades
        ) = backtest_stock(
            ticker,
            stock_data
        )

        all_trades.extend(trades)

        results.append({
            "Ticker": ticker,
            "Final_Capital": final_capital,
            "Strategy_Return": strategy_return,
            "Buy_Hold_Return": buy_hold_return,
            "Max_Drawdown": max_drawdown,
            "Trades": len(trades)
        })

        print(
            f"  -> Trades: {len(trades)} | "
            f"Strategy: {strategy_return:.2%} | "
            f"B&H: {buy_hold_return:.2%}"
        )

    except Exception as e:

        print(
            f"  -> ERREUR sur {ticker}: {e}"
        )


# ============================================================
# EXPORT DES TRADES
# ============================================================

trades_df = pd.DataFrame(all_trades)

results_df = pd.DataFrame(results)


if not trades_df.empty:

    # Tri chronologique
    trades_df = trades_df.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    # Export détaillé
    trades_df.to_csv(
        "all_trades.csv",
        index=False
    )

    # Export utilisé par les analyses
    trades_df.to_csv(
        "trades_autopsy.csv",
        index=False
    )

else:

    print()
    print("ATTENTION : aucun trade généré.")


# ============================================================
# EXPORT DES RESULTATS
# ============================================================

if not results_df.empty:

    results_df = results_df.sort_values(
        "Ticker"
    )

    results_df.to_csv(
        "backtest_results.csv",
        index=False
    )


# ============================================================
# RESUME FINAL
# ============================================================

print()
print("=" * 70)
print("BACKTEST TERMINE")
print("=" * 70)
print()

if not results_df.empty:

    print(
        f"Actions analysées : "
        f"{len(results_df)}"
    )

    print(
        f"Nombre total de trades : "
        f"{len(trades_df)}"
    )

    print()

    print(
        results_df[
            [
                "Ticker",
                "Strategy_Return",
                "Buy_Hold_Return",
                "Max_Drawdown",
                "Trades"
            ]
        ].to_string(index=False)
    )

    print()

    print("Fichiers créés :")
    print("  - all_trades.csv")
    print("  - trades_autopsy.csv")
    print("  - backtest_results.csv")

    print()

    # Statistiques globales
    if not trades_df.empty:

        winners = (
            trades_df["PnL_Pct"] > 0
        ).sum()

        losers = (
            trades_df["PnL_Pct"] <= 0
        ).sum()

        win_rate = (
            winners / len(trades_df)
            if len(trades_df) > 0
            else 0
        )

        avg_pnl = trades_df["PnL_Pct"].mean()

        print("STATISTIQUES GLOBALES")
        print("-" * 70)

        print(
            f"Trades gagnants : {winners}"
        )

        print(
            f"Trades perdants : {losers}"
        )

        print(
            f"Taux de réussite : {win_rate:.2%}"
        )

        print(
            f"PnL moyen par trade : {avg_pnl:.2%}"
        )

print()
print("=" * 70)
print("FIN")
print("=" * 70)
print()