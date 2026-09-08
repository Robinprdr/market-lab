import os
import numpy as np
import pandas as pd
import yfinance as yf

# ============================================================
# SHORT MOMENTUM V1 — RESEARCH
# ============================================================
# Objectif :
# Identifier les conditions dans lesquelles une action qui baisse
# continue statistiquement à baisser à court terme.
#
# Convention IMPORTANTE :
# Future_Return_N = Close[t+N] / Open[t+1] - 1
#
# Pour une stratégie SHORT :
#   rendement futur négatif = BON pour le short
#   rendement futur positif = MAUVAIS pour le short
#
# Exemple :
#   entrée à 100
#   sortie à 95
#   Future_Return = 95/100 - 1 = -5%
#   => +5% pour le short
# ============================================================

START_DATE = "2018-01-01"
END_DATE = "2025-12-20"

TICKERS = [
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "GOOGL", "META", "NFLX", "DIS", "AMZN", "TSLA",
    "HD", "NKE", "MCD", "LOW", "JPM", "BAC", "GS", "MS",
    "V", "MA", "BLK", "UNH", "JNJ", "LLY", "MRK", "ABBV",
    "PFE", "CAT", "GE", "HON", "UPS", "BA", "XOM", "CVX",
    "COP", "WMT", "COST", "KO", "PEP", "PLD", "AMT", "NEE",
    "DUK"
]

SPY = "SPY"

OUTPUT = "results/short_momentum/short_momentum_v1_research.csv"


def download_data(ticker):
    print(f"Téléchargement {ticker}...")

    df = yf.download(
        ticker,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False
    )

    if df.empty:
        print(f"⚠️ Aucune donnée pour {ticker}")
        return None

    # yfinance peut retourner un MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close", "Volume"]

    missing = [c for c in required if c not in df.columns]

    if missing:
        print(f"⚠️ {ticker}: colonnes manquantes {missing}")
        return None

    df = df[required].copy()
    df = df.dropna()

    return df


def calculate_features(df):
    df = df.copy()

    # --------------------------------------------------------
    # Returns historiques
    # --------------------------------------------------------

    df["Return_1D"] = df["Close"].pct_change(1)
    df["Return_3D"] = df["Close"].pct_change(3)
    df["Return_5D"] = df["Close"].pct_change(5)
    df["Return_10D"] = df["Close"].pct_change(10)
    df["Return_20D"] = df["Close"].pct_change(20)

    # --------------------------------------------------------
    # Moyennes mobiles
    # --------------------------------------------------------

    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()

    df["Distance_SMA20"] = df["Close"] / df["SMA20"] - 1
    df["Distance_SMA50"] = df["Close"] / df["SMA50"] - 1
    df["Distance_SMA200"] = df["Close"] / df["SMA200"] - 1

    df["SMA20_vs_SMA50"] = df["SMA20"] / df["SMA50"] - 1
    df["SMA50_vs_SMA200"] = df["SMA50"] / df["SMA200"] - 1

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    df["Volume_Moyen_20"] = df["Volume"].rolling(20).mean()
    df["Volume_Ratio"] = (
        df["Volume"] / df["Volume_Moyen_20"]
    )

    # --------------------------------------------------------
    # ATR
    # --------------------------------------------------------

    previous_close = df["Close"].shift(1)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - previous_close).abs()
    tr3 = (df["Low"] - previous_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    df["ATR14"] = true_range.rolling(14).mean()
    df["ATR_Pct"] = df["ATR14"] / df["Close"]

    # --------------------------------------------------------
    # Nombre de jours baissiers
    # --------------------------------------------------------

    df["Negative_Days_5"] = (
        (df["Return_1D"] < 0)
        .rolling(5)
        .sum()
    )

    df["Negative_Days_10"] = (
        (df["Return_1D"] < 0)
        .rolling(10)
        .sum()
    )

    # --------------------------------------------------------
    # Jours consécutifs de baisse
    # --------------------------------------------------------

    down = df["Return_1D"] < 0

    consecutive = []
    count = 0

    for value in down:
        if value:
            count += 1
        else:
            count = 0

        consecutive.append(count)

    df["Consecutive_Down_Days"] = consecutive

    # --------------------------------------------------------
    # Performance cumulative pendant la séquence baissière
    # --------------------------------------------------------

    df["Return_Consecutive_Down"] = np.nan

    for i in range(len(df)):
        n = df["Consecutive_Down_Days"].iloc[i]

        if n > 0 and i >= n:
            start_price = df["Close"].iloc[i - n]
            end_price = df["Close"].iloc[i]

            if start_price != 0:
                df.loc[df.index[i], "Return_Consecutive_Down"] = (
                    end_price / start_price - 1
                )

    # --------------------------------------------------------
    # Accélération du momentum
    # --------------------------------------------------------

    df["Momentum_Acceleration_5D"] = (
        df["Return_5D"] - df["Return_10D"] / 2
    )

    # --------------------------------------------------------
    # FUTURE RETURNS
    #
    # Signal = jour t
    # Entrée = Open t+1
    #
    # IMPORTANT :
    # On utilise ici la convention commune aux stratégies :
    #
    # Future_Return_N =
    #     Close[t+N] / Open[t+1] - 1
    #
    # Donc :
    #   négatif = action baisse = favorable au SHORT
    #   positif = action monte = défavorable au SHORT
    # --------------------------------------------------------

    df["Future_Return_1D"] = (
        df["Close"].shift(-1) /
        df["Open"].shift(-1) - 1
    )

    df["Future_Return_3D"] = (
        df["Close"].shift(-3) /
        df["Open"].shift(-1) - 1
    )

    df["Future_Return_5D"] = (
        df["Close"].shift(-5) /
        df["Open"].shift(-1) - 1
    )

    df["Future_Return_10D"] = (
        df["Close"].shift(-10) /
        df["Open"].shift(-1) - 1
    )

    return df


def build_spy_features():
    print("\nTéléchargement SPY...")

    spy = download_data(SPY)

    if spy is None:
        raise RuntimeError("Impossible de télécharger SPY.")

    spy["SPY_Return_1D"] = spy["Close"].pct_change(1)
    spy["SPY_Return_5D"] = spy["Close"].pct_change(5)
    spy["SPY_Return_10D"] = spy["Close"].pct_change(10)

    spy["SPY_SMA50"] = spy["Close"].rolling(50).mean()

    spy["SPY_Distance_SMA50"] = (
        spy["Close"] / spy["SPY_SMA50"] - 1
    )

    spy["SPY_Volume_Moyen_20"] = (
        spy["Volume"].rolling(20).mean()
    )

    spy["SPY_Volume_Ratio"] = (
        spy["Volume"] /
        spy["SPY_Volume_Moyen_20"]
    )

    return spy[
        [
            "SPY_Return_1D",
            "SPY_Return_5D",
            "SPY_Return_10D",
            "SPY_Distance_SMA50",
            "SPY_Volume_Ratio"
        ]
    ]


def main():

    os.makedirs(
        os.path.dirname(OUTPUT),
        exist_ok=True
    )

    # --------------------------------------------------------
    # SPY factor
    # --------------------------------------------------------

    spy_features = build_spy_features()

    all_data = []

    # --------------------------------------------------------
    # Actions
    # --------------------------------------------------------

    for ticker in TICKERS:

        df = download_data(ticker)

        if df is None:
            continue

        df = calculate_features(df)

        df["Ticker"] = ticker

        df = df.reset_index()

        # Uniformiser le nom de la date
        if "Date" not in df.columns:
            df = df.rename(
                columns={df.columns[0]: "Date"}
            )

        # Ajouter facteurs SPY
        df = df.merge(
            spy_features.reset_index(),
            on="Date",
            how="left"
        )

        all_data.append(df)

    if not all_data:
        raise RuntimeError(
            "Aucune donnée disponible."
        )

    result = pd.concat(
        all_data,
        ignore_index=True
    )

    # --------------------------------------------------------
    # Nettoyage
    # --------------------------------------------------------

    result = result.sort_values(
        ["Date", "Ticker"]
    ).reset_index(drop=True)

    # On retire uniquement les lignes qui ne peuvent pas
    # avoir les facteurs / futures nécessaires.
    required_columns = [
        "ATR_Pct",
        "Return_3D",
        "Future_Return_1D",
        "Future_Return_3D",
        "Future_Return_5D",
        "Future_Return_10D"
    ]

    result = result.dropna(
        subset=required_columns
    )

    # --------------------------------------------------------
    # Sauvegarde
    # --------------------------------------------------------

    result.to_csv(
        OUTPUT,
        index=False
    )

    # --------------------------------------------------------
    # Rapport
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("SHORT MOMENTUM V1 — RESEARCH CORRIGÉ")
    print("=" * 70)

    print(f"Rows       : {len(result):,}")
    print(f"Stocks     : {result['Ticker'].nunique()}")
    print(
        f"Date       : "
        f"{result['Date'].min().date()} → "
        f"{result['Date'].max().date()}"
    )

    print("\nFuture returns :")
    print(
        "IMPORTANT : négatif = favorable au SHORT"
    )

    for horizon in [1, 3, 5, 10]:

        col = f"Future_Return_{horizon}D"

        mean = result[col].mean()
        median = result[col].median()

        # Pour un short, une observation est gagnante
        # si le rendement de l'action est négatif.
        win_rate = (
            result[col] < 0
        ).mean()

        print(
            f"{horizon:>2}D : "
            f"mean {mean:+.3%} | "
            f"median {median:+.3%} | "
            f"WR {win_rate:.1%} | "
            f"n {result[col].count():,}"
        )

    print("\nColonnes principales :")
    print(
        [
            "Return_1D",
            "Return_3D",
            "Return_5D",
            "Return_10D",
            "Return_20D",
            "Distance_SMA20",
            "Distance_SMA50",
            "Distance_SMA200",
            "Volume_Ratio",
            "ATR_Pct",
            "Negative_Days_5",
            "Negative_Days_10",
            "Consecutive_Down_Days",
            "Return_Consecutive_Down",
            "Momentum_Acceleration_5D",
            "SPY_Return_10D",
            "Future_Return_1D",
            "Future_Return_3D",
            "Future_Return_5D",
            "Future_Return_10D"
        ]
    )

    print(
        f"\nFichier créé : {OUTPUT}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
