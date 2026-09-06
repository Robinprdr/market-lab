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
# TELECHARGEMENT
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
# ANALYSE D'UNE ACTION
# ============================================================

all_trades = []

for ticker in TICKERS:

    try:
        df = pd.DataFrame({
            "Open": data["Open"][ticker],
            "High": data["High"][ticker],
            "Low": data["Low"][ticker],
            "Close": data["Close"][ticker],
            "Volume": data["Volume"][ticker],
        }).dropna()

        if len(df) < 100:
            continue

        # ----------------------------------------------------
        # INDICATEURS
        # ----------------------------------------------------

        df["Return"] = df["Close"].pct_change()

        df["SMA20"] = df["Close"].rolling(20).mean()
        df["SMA50"] = df["Close"].rolling(50).mean()
        df["SMA200"] = df["Close"].rolling(200).mean()

        df["Volume20"] = df["Volume"].rolling(20).mean()

        # ATR 14
        previous_close = df["Close"].shift(1)

        tr1 = df["High"] - df["Low"]
        tr2 = abs(df["High"] - previous_close)
        tr3 = abs(df["Low"] - previous_close)

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        df["ATR14"] = true_range.rolling(14).mean()
        df["ATR_Pct"] = df["ATR14"] / df["Close"]

        # ----------------------------------------------------
        # VARIABLES SUPPLÉMENTAIRES
        # ----------------------------------------------------

        df["Distance_SMA20"] = df["Close"] / df["SMA20"] - 1
        df["Distance_SMA50"] = df["Close"] / df["SMA50"] - 1
        df["Distance_SMA200"] = df["Close"] / df["SMA200"] - 1

        df["Volume_Ratio"] = df["Volume"] / df["Volume20"]

        df["Return_3D"] = df["Close"].pct_change(3)
        df["Return_5D"] = df["Close"].pct_change(5)
        df["Return_10D"] = df["Close"].pct_change(10)

        # Nombre de jours négatifs sur les 5 derniers jours
        df["Negative_Days_5"] = (
            (df["Return"] < 0)
            .rolling(5)
            .sum()
        )

        # Chute précédente
        df["Signal_Drop"] = df["Return"]

        # ----------------------------------------------------
        # SIGNAL
        # ----------------------------------------------------

        for i in range(200, len(df) - 1):

            signal = df.iloc[i]

            if signal["Signal_Drop"] > DROP_THRESHOLD:
                continue

            if signal["Close"] <= signal["SMA50"]:
                continue

            if signal["Volume"] <= signal["Volume20"]:
                continue

            entry_day = i + 1

            entry_price = df.iloc[entry_day]["Open"]

            if pd.isna(entry_price):
                continue

            # ------------------------------------------------
            # VARIABLES DU SIGNAL
            # ------------------------------------------------

            signal_drop = signal["Signal_Drop"]
            atr_pct = signal["ATR_Pct"]
            volume_ratio = signal["Volume_Ratio"]

            distance_sma20 = signal["Distance_SMA20"]
            distance_sma50 = signal["Distance_SMA50"]
            distance_sma200 = signal["Distance_SMA200"]

            return_3d = signal["Return_3D"]
            return_5d = signal["Return_5D"]
            return_10d = signal["Return_10D"]

            negative_days_5 = signal["Negative_Days_5"]

            drop_atr_ratio = abs(signal_drop) / atr_pct if atr_pct > 0 else np.nan

            # ------------------------------------------------
            # SORTIE
            # ------------------------------------------------

            exit_price = None
            exit_type = None
            holding_days = None

            last_day = min(
                entry_day + MAX_HOLDING_DAYS - 1,
                len(df) - 1
            )

            for j in range(entry_day, last_day + 1):

                day = df.iloc[j]

                stop_price = entry_price * (1 + SL_PCT)
                target_price = entry_price * (1 + TP_PCT)

                hit_stop = day["Low"] <= stop_price
                hit_target = day["High"] >= target_price

                # Si SL et TP sont touchés le même jour,
                # on choisit volontairement le SL.
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

            all_trades.append({
                "Ticker": ticker,
                "Date": signal.name,

                "Signal_Drop": signal_drop,
                "ATR_Pct": atr_pct,
                "Drop_ATR_Ratio": drop_atr_ratio,
                "Volume_Ratio": volume_ratio,

                "Distance_SMA20": distance_sma20,
                "Distance_SMA50": distance_sma50,
                "Distance_SMA200": distance_sma200,

                "Return_3D": return_3d,
                "Return_5D": return_5d,
                "Return_10D": return_10d,

                "Negative_Days_5": negative_days_5,

                "Holding_Days": holding_days,
                "PnL_Pct": pnl_pct,
                "Exit": exit_type,
            })

    except Exception as e:
        print(f"Erreur {ticker}: {e}")

# ============================================================
# DATAFRAME
# ============================================================

trades = pd.DataFrame(all_trades)

if trades.empty:
    print("Aucun trade trouvé.")
    raise SystemExit

trades = trades.replace([np.inf, -np.inf], np.nan)
trades = trades.dropna()

print()
print("=" * 70)
print("AUTOPSIE DES TRADES PERDANTS")
print("=" * 70)

print(f"\nNombre total de trades : {len(trades)}")

losers = trades[trades["PnL_Pct"] < 0].copy()
winners = trades[trades["PnL_Pct"] > 0].copy()

print(f"Gagnants : {len(winners)}")
print(f"Perdants : {len(losers)}")

# ============================================================
# COMPARAISON GAGNANTS / PERDANTS
# ============================================================

columns = [
    "Signal_Drop",
    "ATR_Pct",
    "Drop_ATR_Ratio",
    "Volume_Ratio",
    "Distance_SMA20",
    "Distance_SMA50",
    "Distance_SMA200",
    "Return_3D",
    "Return_5D",
    "Return_10D",
    "Negative_Days_5",
    "Holding_Days",
]

print("\n" + "=" * 70)
print("GAGNANTS VS PERDANTS")
print("=" * 70)

for col in columns:

    winner_mean = winners[col].mean()
    loser_mean = losers[col].mean()

    difference = winner_mean - loser_mean

    print(
        f"{col:20s} | "
        f"Gagnants {winner_mean:+.4f} | "
        f"Perdants {loser_mean:+.4f} | "
        f"Diff {difference:+.4f}"
    )

# ============================================================
# DISTRIBUTION DES PERDANTS
# ============================================================

print("\n" + "=" * 70)
print("PROFIL DES PERDANTS")
print("=" * 70)

print("\n1. TAILLE DE LA CHUTE")

bins = [-np.inf, -0.04, -0.03, -0.025, -0.02]
labels = [
    "< -4%",
    "-4% à -3%",
    "-3% à -2.5%",
    "-2.5% à -2%"
]

losers["Drop_Group"] = pd.cut(
    losers["Signal_Drop"],
    bins=bins,
    labels=labels
)

for group, subset in losers.groupby(
    "Drop_Group",
    observed=False
):

    if len(subset) == 0:
        continue

    print(
        f"{str(group):20s} | "
        f"{len(subset):4d} perdants | "
        f"perte moyenne {subset['PnL_Pct'].mean():+.3%}"
    )

# ============================================================
# ATR
# ============================================================

print("\n2. CHUTE / ATR")

bins = [-np.inf, 0.5, 1, 1.5, 2, np.inf]
labels = [
    "< 0.5 ATR",
    "0.5 - 1 ATR",
    "1 - 1.5 ATR",
    "1.5 - 2 ATR",
    "> 2 ATR"
]

losers["ATR_Group"] = pd.cut(
    losers["Drop_ATR_Ratio"],
    bins=bins,
    labels=labels
)

for group, subset in losers.groupby(
    "ATR_Group",
    observed=False
):

    if len(subset) == 0:
        continue

    print(
        f"{str(group):20s} | "
        f"{len(subset):4d} perdants | "
        f"perte moyenne {subset['PnL_Pct'].mean():+.3%}"
    )

# ============================================================
# VOLUME
# ============================================================

print("\n3. VOLUME")

bins = [1, 1.25, 1.5, 2, np.inf]
labels = [
    "1 - 1.25x",
    "1.25 - 1.5x",
    "1.5 - 2x",
    "> 2x"
]

losers["Volume_Group"] = pd.cut(
    losers["Volume_Ratio"],
    bins=bins,
    labels=labels
)

for group, subset in losers.groupby(
    "Volume_Group",
    observed=False
):

    if len(subset) == 0:
        continue

    print(
        f"{str(group):20s} | "
        f"{len(subset):4d} perdants | "
        f"perte moyenne {subset['PnL_Pct'].mean():+.3%}"
    )

# ============================================================
# DISTANCE SMA50
# ============================================================

print("\n4. DISTANCE SMA50")

bins = [-np.inf, 0.02, 0.05, 0.10, 0.20, np.inf]
labels = [
    "< 2%",
    "2 - 5%",
    "5 - 10%",
    "10 - 20%",
    "> 20%"
]

losers["SMA50_Group"] = pd.cut(
    losers["Distance_SMA50"],
    bins=bins,
    labels=labels
)

for group, subset in losers.groupby(
    "SMA50_Group",
    observed=False
):

    if len(subset) == 0:
        continue

    print(
        f"{str(group):20s} | "
        f"{len(subset):4d} perdants | "
        f"perte moyenne {subset['PnL_Pct'].mean():+.3%}"
    )

# ============================================================
# TENDANCE
# ============================================================

print("\n5. TENDANCE")

print("\nPerdants avec prix sous SMA200 :")
subset = losers[losers["Distance_SMA200"] < 0]

print(
    f"{len(subset)} / {len(losers)} "
    f"({len(subset)/len(losers):.1%})"
)

print("\nPerdants avec baisse sur 5 jours :")
subset = losers[losers["Return_5D"] < 0]

print(
    f"{len(subset)} / {len(losers)} "
    f"({len(subset)/len(losers):.1%})"
)

print("\nPerdants avec au moins 3 jours rouges sur les 5 derniers jours :")
subset = losers[losers["Negative_Days_5"] >= 3]

print(
    f"{len(subset)} / {len(losers)} "
    f"({len(subset)/len(losers):.1%})"
)

# ============================================================
# PIRE PROFIL
# ============================================================

print("\n" + "=" * 70)
print("LES 20 PERDANTS LES PLUS INTÉRESSANTS À ÉTUDIER")
print("=" * 70)

worst = losers.sort_values("PnL_Pct").head(20)

print(
    worst[
        [
            "Ticker",
            "Date",
            "Signal_Drop",
            "Drop_ATR_Ratio",
            "Volume_Ratio",
            "Distance_SMA50",
            "Distance_SMA200",
            "Return_5D",
            "Negative_Days_5",
            "PnL_Pct",
            "Exit",
        ]
    ].to_string(index=False)
)

# ============================================================
# SAUVEGARDE
# ============================================================

trades.to_csv("results/mean_reversion/trades_autopsy.csv", index=False)

print("\n" + "=" * 70)
print("Analyse terminée.")
print("Fichier créé : results/mean_reversion/trades_autopsy.csv")
print("=" * 70)