from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


# ============================================================
# CONFIGURATION
# ============================================================

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "GOOGL", "META", "NFLX", "DIS", "AMZN", "TSLA",
    "HD", "NKE", "MCD", "LOW", "JPM", "BAC", "GS", "MS",
    "V", "MA", "BLK", "UNH", "JNJ", "LLY", "MRK", "ABBV",
    "PFE", "CAT", "GE", "HON", "UPS", "BA", "XOM", "CVX",
    "COP", "WMT", "COST", "KO", "PEP", "PLD", "AMT", "NEE",
    "DUK",
]

MARKET_TICKER = "SPY"

START_DATE = "2018-01-01"
END_DATE = "2025-12-20"

OUTPUT_DIR = Path("results/momentum")
OUTPUT_FILE = OUTPUT_DIR / "momentum_v1_research.csv"


# ============================================================
# INDICATEURS
# ============================================================

def calculate_indicators(df):

    df = df.copy()

    df["Return_1D"] = df["Close"].pct_change(1)
    df["Return_3D"] = df["Close"].pct_change(3)
    df["Return_5D"] = df["Close"].pct_change(5)
    df["Return_10D"] = df["Close"].pct_change(10)
    df["Return_20D"] = df["Close"].pct_change(20)

    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    df["Distance_SMA20"] = (
        df["Close"] / df["SMA20"] - 1
    )

    df["Distance_SMA50"] = (
        df["Close"] / df["SMA50"] - 1
    )

    df["Distance_SMA200"] = (
        df["Close"] / df["SMA200"] - 1
    )

    df["SMA20_vs_SMA50"] = (
        df["SMA20"] / df["SMA50"] - 1
    )

    df["SMA50_vs_SMA200"] = (
        df["SMA50"] / df["SMA200"] - 1
    )

    df["Volume_Moyen_20"] = (
        df["Volume"].rolling(20).mean()
    )

    df["Volume_Ratio"] = (
        df["Volume"] / df["Volume_Moyen_20"]
    )

    previous_close = df["Close"].shift(1)

    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    df["ATR14"] = true_range.rolling(14).mean()

    df["ATR_Pct"] = (
        df["ATR14"] / df["Close"]
    )

    df["Positive_Days_5"] = (
        df["Return_1D"]
        .gt(0)
        .rolling(5)
        .sum()
    )

    df["Positive_Days_10"] = (
        df["Return_1D"]
        .gt(0)
        .rolling(10)
        .sum()
    )

    df["Momentum_Acceleration_5D"] = (
        df["Return_5D"]
        - df["Return_10D"] / 2
    )

    return df


# ============================================================
# RENDEMENTS FUTURS
# ============================================================

def calculate_future_returns(df):

    df = df.copy()

    # Entrée théorique :
    # OPEN du jour suivant le signal.

    next_open = df["Open"].shift(-1)

    df["Future_Return_1D"] = (
        df["Close"].shift(-1) / next_open - 1
    )

    df["Future_Return_3D"] = (
        df["Close"].shift(-3) / next_open - 1
    )

    df["Future_Return_5D"] = (
        df["Close"].shift(-5) / next_open - 1
    )

    df["Future_Return_10D"] = (
        df["Close"].shift(-10) / next_open - 1
    )

    return df


# ============================================================
# TÉLÉCHARGEMENT
# ============================================================

def download_data():

    print("=" * 70)
    print("MOMENTUM V1 - RESEARCH DATASET")
    print("=" * 70)

    all_tickers = TICKERS + [MARKET_TICKER]

    print()
    print(
        f"Téléchargement de {len(all_tickers)} actifs..."
    )

    data = yf.download(
        all_tickers,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    return data


# ============================================================
# PRÉPARATION D'UNE ACTION
# ============================================================

def prepare_stock_data(data, ticker):

    try:
        df = data[ticker].copy()
    except KeyError:
        return None

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    if not all(
        column in df.columns
        for column in required_columns
    ):
        return None

    df = df[
        required_columns
    ].copy()

    # --------------------------------------------------------
    # CORRECTION IMPORTANTE :
    # on transforme l'index Date en vraie colonne.
    # --------------------------------------------------------

    df.index.name = "Date"

    df = df.reset_index()

    df = df.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close",
        ]
    )

    df = calculate_indicators(df)

    df = calculate_future_returns(df)

    df["Ticker"] = ticker

    return df


# ============================================================
# PRÉPARATION SPY
# ============================================================

def prepare_market_data(data):

    spy = prepare_stock_data(
        data,
        MARKET_TICKER,
    )

    if spy is None:
        raise RuntimeError(
            "Impossible de préparer les données SPY."
        )

    market = spy[
        [
            "Date",
            "SPY_Return_1D"
            if "SPY_Return_1D" in spy.columns
            else "Return_1D",
        ]
    ].copy()

    # On reconstruit explicitement les facteurs SPY
    # pour éviter toute ambiguïté de nommage.

    market = spy[
        [
            "Date",
            "Return_1D",
            "Return_5D",
            "Return_10D",
            "Distance_SMA50",
            "Volume_Ratio",
        ]
    ].copy()

    market = market.rename(
        columns={
            "Return_1D": "SPY_Return_1D",
            "Return_5D": "SPY_Return_5D",
            "Return_10D": "SPY_Return_10D",
            "Distance_SMA50":
                "SPY_Distance_SMA50",
            "Volume_Ratio":
                "SPY_Volume_Ratio",
        }
    )

    return market


# ============================================================
# DATASET FINAL
# ============================================================

def build_dataset(data):

    market = prepare_market_data(data)

    all_rows = []

    print()
    print("Préparation des actions...")

    for ticker in TICKERS:

        print(f"  {ticker}")

        df = prepare_stock_data(
            data,
            ticker,
        )

        if df is None:
            print(
                "    ⚠ données indisponibles"
            )
            continue

        # ----------------------------------------------------
        # Sécurité supplémentaire :
        # Date doit être uniquement une colonne.
        # ----------------------------------------------------

        if "Date" in df.index.names:
            df = df.reset_index(drop=True)

        market_for_merge = market.copy()

        if "Date" in market_for_merge.index.names:
            market_for_merge = (
                market_for_merge
                .reset_index(drop=True)
            )

        market_for_merge = (
            market_for_merge
            .drop_duplicates("Date")
        )

        df = df.merge(
            market_for_merge,
            on="Date",
            how="left",
        )

        all_rows.append(df)

    if not all_rows:
        raise RuntimeError(
            "Aucune donnée exploitable."
        )

    result = pd.concat(
        all_rows,
        ignore_index=True,
    )

    result = result.sort_values(
        ["Ticker", "Date"]
    ).reset_index(drop=True)

    # ========================================================
    # FACTEURS
    # ========================================================

    factor_columns = [
        "Return_1D",
        "Return_3D",
        "Return_5D",
        "Return_10D",
        "Return_20D",
        "Distance_SMA20",
        "Distance_SMA50",
        "Distance_SMA200",
        "SMA20_vs_SMA50",
        "SMA50_vs_SMA200",
        "Volume_Ratio",
        "ATR_Pct",
        "Positive_Days_5",
        "Positive_Days_10",
        "Momentum_Acceleration_5D",
        "SPY_Return_1D",
        "SPY_Return_5D",
        "SPY_Return_10D",
        "SPY_Distance_SMA50",
        "SPY_Volume_Ratio",
    ]

    # ========================================================
    # TARGETS
    # ========================================================

    target_columns = [
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
        "Future_Return_10D",
    ]

    required_columns = (
        factor_columns
        + target_columns
    )

    result = result.dropna(
        subset=required_columns
    ).reset_index(drop=True)

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    data = download_data()

    print()
    print("✓ Données téléchargées")

    result = build_dataset(data)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print()
    print("=" * 70)
    print("DATASET MOMENTUM V1 TERMINÉ")
    print("=" * 70)

    print()
    print(
        f"Lignes : {len(result):,}"
    )

    print(
        f"Actions : {result['Ticker'].nunique()}"
    )

    print(
        f"Période : "
        f"{result['Date'].min()} → "
        f"{result['Date'].max()}"
    )

    print()
    print("Rendements futurs corrigés :")

    for target in [
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
        "Future_Return_10D",
    ]:

        average = (
            result[target].mean() * 100
        )

        print(
            f"  ✓ {target}: "
            f"{average:+.3f}%"
        )

    print()
    print(
        f"✓ Fichier créé : {OUTPUT_FILE}"
    )

    print()
    print(
        "IMPORTANT : "
        "le signal est observé à la clôture de J "
        "et l'entrée théorique se fait à l'ouverture de J+1."
    )

    print()
    print(
        "Momentum V1 Research terminée."
    )


if __name__ == "__main__":
    main()