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

START_DATE = "2018-01-01"
END_DATE = "2026-01-01"

DROP_THRESHOLD = -0.02
SL_PCT = -0.02
TP_PCT = 0.04
MAX_HOLDING_DAYS = 5

# ============================================================
# BACKTEST D'UNE PÉRIODE
# ============================================================

def backtest_period(df, start_date, end_date, filter_name):

    trades = []

    period = df[
        (df.index >= start_date) &
        (df.index < end_date)
    ].copy()

    if len(period) < 10:
        return []

    for i in range(len(period) - 1):

        signal = period.iloc[i]

        # ----------------------------------------------------
        # STRATÉGIE DE BASE
        # ----------------------------------------------------

        if signal["Signal_Drop"] > DROP_THRESHOLD:
            continue

        if signal["Close"] <= signal["SMA50"]:
            continue

        if signal["Volume"] <= signal["Volume20"]:
            continue

        # ----------------------------------------------------
        # FILTRES À TESTER
        # ----------------------------------------------------

        if filter_name == "NO_FILTER":
            pass

        elif filter_name == "NO_BIG_DROP":
            if signal["Signal_Drop"] < -0.04:
                continue

        elif filter_name == "NO_BIG_DROP_ATR":
            if (
                signal["Signal_Drop"] < -0.04
                and signal["Drop_ATR_Ratio"] > 1.5
            ):
                continue

        elif filter_name == "NO_BIG_DROP_VOLUME":
            if (
                signal["Signal_Drop"] < -0.04
                and signal["Volume_Ratio"] > 2
            ):
                continue

        elif filter_name == "NO_COMBO_3":
            if (
                signal["Signal_Drop"] < -0.04
                and signal["Drop_ATR_Ratio"] > 1.5
                and signal["Return_5D"] < 0
            ):
                continue

        entry_day = i + 1

        if entry_day >= len(period):
            continue

        entry_price = period.iloc[entry_day]["Open"]

        if pd.isna(entry_price) or entry_price <= 0:
            continue

        stop_price = entry_price * (1 + SL_PCT)
        target_price = entry_price * (1 + TP_PCT)

        exit_price = None
        exit_type = None
        holding_days = None

        last_day = min(
            entry_day + MAX_HOLDING_DAYS - 1,
            len(period) - 1
        )

        for j in range(entry_day, last_day + 1):

            day = period.iloc[j]

            hit_stop = day["Low"] <= stop_price
            hit_target = day["High"] >= target_price

            # Conservateur :
            # si SL et TP sont touchés le même jour,
            # on considère que le SL arrive en premier.

            if hit_stop and hit_target:

                exit_price = stop_price
                exit_type = "SL"
                holding_days = j - entry_day + 1
                break

            elif hit_stop:

                exit_price = stop_price
                exit_type = "SL"
                holding_days = j - entry_day + 1
                break

            elif hit_target:

                exit_price = target_price
                exit_type = "TP"
                holding_days = j - entry_day + 1
                break

            elif j == last_day:

                exit_price = day["Close"]
                exit_type = "TIME"
                holding_days = j - entry_day + 1
                break

        if exit_price is None:
            continue

        pnl_pct = exit_price / entry_price - 1

        trades.append({
            "Ticker": df.attrs.get("ticker", ""),
            "Signal_Date": signal.name,
            "PnL_Pct": pnl_pct,
            "Exit": exit_type,
            "Holding_Days": holding_days
        })

    return trades


# ============================================================
# TÉLÉCHARGEMENT
# ============================================================

print("Téléchargement des données...")

data = yf.download(
    TICKERS,
    start=START_DATE,
    end=END_DATE,
    auto_adjust=False,
    progress=False
)

# ============================================================
# PRÉPARATION DES DONNÉES
# ============================================================

all_data = {}

for ticker in TICKERS:

    try:

        df = pd.DataFrame({
            "Open": data["Open"][ticker],
            "High": data["High"][ticker],
            "Low": data["Low"][ticker],
            "Close": data["Close"][ticker],
            "Volume": data["Volume"][ticker],
        }).dropna()

        if len(df) < 250:
            continue

        # ----------------------------------------------------
        # INDICATEURS
        # ----------------------------------------------------

        df["Return"] = df["Close"].pct_change()

        df["SMA50"] = df["Close"].rolling(50).mean()

        df["Volume20"] = df["Volume"].rolling(20).mean()

        previous_close = df["Close"].shift(1)

        tr1 = df["High"] - df["Low"]
        tr2 = abs(df["High"] - previous_close)
        tr3 = abs(df["Low"] - previous_close)

        true_range = pd.concat(
            [tr1, tr2, tr3],
            axis=1
        ).max(axis=1)

        df["ATR14"] = true_range.rolling(14).mean()

        df["ATR_Pct"] = df["ATR14"] / df["Close"]

        df["Volume_Ratio"] = (
            df["Volume"] / df["Volume20"]
        )

        df["Signal_Drop"] = df["Return"]

        df["Drop_ATR_Ratio"] = (
            abs(df["Signal_Drop"]) / df["ATR_Pct"]
        )

        df["Return_5D"] = df["Close"].pct_change(5)

        df.attrs["ticker"] = ticker

        all_data[ticker] = df

    except Exception as e:

        print(f"Erreur {ticker}: {e}")


# ============================================================
# DÉFINITION DES PÉRIODES
# ============================================================

TRAIN_START = "2018-01-01"
TRAIN_END = "2023-01-01"

TEST_START = "2023-01-01"
TEST_END = "2026-01-01"

FILTERS = [
    "NO_FILTER",
    "NO_BIG_DROP",
    "NO_BIG_DROP_ATR",
    "NO_BIG_DROP_VOLUME",
    "NO_COMBO_3"
]

FILTER_LABELS = {
    "NO_FILTER": "BASE",
    "NO_BIG_DROP": "Exclut chute >4%",
    "NO_BIG_DROP_ATR": "Exclut chute >4% + ATR >1.5",
    "NO_BIG_DROP_VOLUME": "Exclut chute >4% + volume >2x",
    "NO_COMBO_3": "Exclut chute >4% + ATR >1.5 + baisse 5J"
}

# ============================================================
# EXÉCUTION
# ============================================================

all_results = []

print("\n" + "=" * 80)
print("TEST HORS ÉCHANTILLON")
print("=" * 80)

print("\nTRAIN :", TRAIN_START, "→", TRAIN_END)
print("TEST  :", TEST_START, "→", TEST_END)

for filter_name in FILTERS:

    train_trades = []
    test_trades = []

    for ticker, df in all_data.items():

        train = backtest_period(
            df,
            TRAIN_START,
            TRAIN_END,
            filter_name
        )

        test = backtest_period(
            df,
            TEST_START,
            TEST_END,
            filter_name
        )

        train_trades.extend(train)
        test_trades.extend(test)

    # --------------------------------------------------------
    # STATISTIQUES
    # --------------------------------------------------------

    def stats(trades):

        if not trades:
            return {
                "trades": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "total_pnl": 0
            }

        pnls = np.array([
            t["PnL_Pct"]
            for t in trades
        ])

        return {
            "trades": len(trades),
            "win_rate": np.mean(pnls > 0),
            "avg_pnl": np.mean(pnls),
            "total_pnl": pnls.sum()
        }

    train_stats = stats(train_trades)
    test_stats = stats(test_trades)

    all_results.append({
        "Filter": FILTER_LABELS[filter_name],

        "Train_Trades": train_stats["trades"],
        "Train_WinRate": train_stats["win_rate"],
        "Train_AvgPnL": train_stats["avg_pnl"],

        "Test_Trades": test_stats["trades"],
        "Test_WinRate": test_stats["win_rate"],
        "Test_AvgPnL": test_stats["avg_pnl"],
    })

# ============================================================
# AFFICHAGE
# ============================================================

results = pd.DataFrame(all_results)

print("\n" + "=" * 80)
print("RÉSULTATS")
print("=" * 80)

for _, row in results.iterrows():

    print("\n" + row["Filter"])

    print(
        f"TRAIN | "
        f"{int(row['Train_Trades'])} trades | "
        f"Win {row['Train_WinRate']:.1%} | "
        f"PnL moyen {row['Train_AvgPnL']:+.3%}"
    )

    print(
        f"TEST  | "
        f"{int(row['Test_Trades'])} trades | "
        f"Win {row['Test_WinRate']:.1%} | "
        f"PnL moyen {row['Test_AvgPnL']:+.3%}"
    )

# ============================================================
# COMPARAISON AVEC LA BASE
# ============================================================

base = results[
    results["Filter"] == "BASE"
].iloc[0]

print("\n" + "=" * 80)
print("IMPACT DES FILTRES SUR LE TEST")
print("=" * 80)

for _, row in results.iterrows():

    if row["Filter"] == "BASE":
        continue

    trade_diff = (
        row["Test_Trades"] - base["Test_Trades"]
    )

    pnl_diff = (
        row["Test_AvgPnL"] - base["Test_AvgPnL"]
    )

    win_diff = (
        row["Test_WinRate"] - base["Test_WinRate"]
    )

    print(
        f"\n{row['Filter']}"
    )

    print(
        f"Trades retirés : {abs(int(trade_diff))}"
    )

    print(
        f"Diff Win Rate : {win_diff:+.1%}"
    )

    print(
        f"Diff PnL moyen : {pnl_diff:+.3%}"
    )

print("\n" + "=" * 80)
print("FIN DU TEST")
print("=" * 80)