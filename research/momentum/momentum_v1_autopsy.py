from pathlib import Path
import pandas as pd
import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================

TRADES_FILE = Path("results/momentum/momentum_v1_trades.csv")


# ============================================================
# OUTILS
# ============================================================

def pct(x):
    return f"{x * 100:.2f}%"


def money(x):
    return f"${x:,.2f}"


def print_separator():
    print("-" * 70)


def stats(df, name):
    if df.empty:
        print(f"\n{name}: aucune donnée")
        return

    pnl = df["PnL"]

    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]

    gross_profit = winners.sum()
    gross_loss = abs(losers.sum())

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    win_rate = (pnl > 0).mean()

    avg_trade = pnl.mean()

    avg_winner = winners.mean() if len(winners) else 0
    avg_loser = losers.mean() if len(losers) else 0

    payoff = (
        avg_winner / abs(avg_loser)
        if avg_loser != 0
        else np.inf
    )

    expectancy = pnl.mean()

    print(f"\n{name}")
    print_separator()
    print(f"Trades             : {len(df):,}")
    print(f"Gagnants           : {len(winners):,}")
    print(f"Perdants           : {len(losers):,}")
    print(f"Win rate           : {pct(win_rate)}")
    print(f"PnL                 : {money(pnl.sum())}")
    print(f"Trade moyen        : {pct(avg_trade)}")
    print(f"Trade médian       : {pct(pnl.median())}")
    print(f"Gain moyen gagnant : {pct(avg_winner)}")
    print(f"Perte moyenne      : {pct(avg_loser)}")
    print(f"Payoff ratio       : {payoff:.2f}")
    print(f"Expectancy         : {pct(expectancy)}")
    print(f"Profit Factor      : {profit_factor:.2f}")


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("MOMENTUM V1 - AUTOPSIE DES TRADES")
print("=" * 70)

if not TRADES_FILE.exists():
    print(f"\nERREUR : fichier introuvable : {TRADES_FILE}")
    print("\nVérifie que tu es bien à la racine du projet.")
    raise SystemExit(1)

df = pd.read_csv(TRADES_FILE)

print(f"\nFichier : {TRADES_FILE}")
print(f"Lignes  : {len(df):,}")

print("\nColonnes détectées :")
print(", ".join(df.columns))


# ============================================================
# NORMALISATION
# ============================================================

# Conversion dates si présentes
for col in ["Signal_Date", "Entry_Date", "Exit_Date"]:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")


# Conversion numérique
for col in [
    "PnL",
    "Return",
    "Entry_Price",
    "Exit_Price",
    "Position_Size",
    "ATR_Pct",
    "Return_10D",
]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")


# ============================================================
# STATISTIQUES GLOBALES
# ============================================================

stats(df, "1. PERFORMANCE GLOBALE")


# ============================================================
# VERIFICATION DU CAPITAL / PNL
# ============================================================

print("\n" + "=" * 70)
print("2. CONTROLE DU PNL")
print("=" * 70)

if "PnL" in df.columns:
    print(f"\nPnL total : {money(df['PnL'].sum())}")

    if "Return" in df.columns:
        print(f"Return moyen par trade : {pct(df['Return'].mean())}")
        print(f"Return médian          : {pct(df['Return'].median())}")

    print("\nDistribution des PnL :")
    print(df["PnL"].describe().to_string())


# ============================================================
# DUREE DES TRADES
# ============================================================

print("\n" + "=" * 70)
print("3. DUREE DES TRADES")
print("=" * 70)

if "Entry_Date" in df.columns and "Exit_Date" in df.columns:

    df["Holding_Days"] = (
        df["Exit_Date"] - df["Entry_Date"]
    ).dt.days

    print("\nDistribution :")
    print(df["Holding_Days"].describe().to_string())

    print("\nPerformance par durée :")

    duration_stats = (
        df.groupby("Holding_Days")
        .agg(
            Trades=("PnL", "size"),
            PnL=("PnL", "sum"),
            Avg_Return=("Return", "mean") if "Return" in df.columns else ("PnL", "mean"),
            Win_Rate=("PnL", lambda x: (x > 0).mean()),
        )
        .sort_index()
    )

    print(duration_stats.to_string())


# ============================================================
# SORTIES SL / TP / TIME
# ============================================================

print("\n" + "=" * 70)
print("4. ANALYSE DES SORTIES")
print("=" * 70)

exit_column = None

for candidate in ["Exit_Reason", "Exit_Type", "Reason"]:
    if candidate in df.columns:
        exit_column = candidate
        break

if exit_column:

    exit_stats = (
        df.groupby(exit_column)
        .agg(
            Trades=("PnL", "size"),
            PnL=("PnL", "sum"),
            Avg_PnL=("PnL", "mean"),
            Win_Rate=("PnL", lambda x: (x > 0).mean()),
        )
        .sort_values("PnL", ascending=False)
    )

    print(exit_stats.to_string())

else:
    print("\nAucune colonne de type Exit_Reason détectée.")


# ============================================================
# PERFORMANCE PAR ANNEE
# ============================================================

print("\n" + "=" * 70)
print("5. PERFORMANCE PAR ANNEE")
print("=" * 70)

if "Exit_Date" in df.columns:

    df["Year"] = df["Exit_Date"].dt.year

    yearly = (
        df.groupby("Year")
        .agg(
            Trades=("PnL", "size"),
            PnL=("PnL", "sum"),
            Avg_PnL=("PnL", "mean"),
            Win_Rate=("PnL", lambda x: (x > 0).mean()),
        )
    )

    print(yearly.to_string())


# ============================================================
# PERFORMANCE PAR ACTION
# ============================================================

print("\n" + "=" * 70)
print("6. PERFORMANCE PAR ACTION")
print("=" * 70)

ticker_column = None

for candidate in ["Ticker", "Symbol", "Stock"]:
    if candidate in df.columns:
        ticker_column = candidate
        break

if ticker_column:

    ticker_stats = (
        df.groupby(ticker_column)
        .agg(
            Trades=("PnL", "size"),
            PnL=("PnL", "sum"),
            Avg_PnL=("PnL", "mean"),
            Win_Rate=("PnL", lambda x: (x > 0).mean()),
        )
        .sort_values("PnL", ascending=False)
    )

    print("\nTOP 15 :")
    print(ticker_stats.head(15).to_string())

    print("\nBOTTOM 15 :")
    print(ticker_stats.tail(15).sort_values("PnL").to_string())

else:
    print("\nAucune colonne Ticker/Symbol/Stock détectée.")


# ============================================================
# MEILLEURS / PIRES TRADES
# ============================================================

print("\n" + "=" * 70)
print("7. MEILLEURS ET PIRES TRADES")
print("=" * 70)

columns_to_show = []

for col in [
    "Ticker",
    "Symbol",
    "Signal_Date",
    "Entry_Date",
    "Exit_Date",
    "Return",
    "PnL",
    "Exit_Reason",
    "ATR_Pct",
    "Return_10D",
]:
    if col in df.columns and col not in columns_to_show:
        columns_to_show.append(col)

if "PnL" in df.columns:

    print("\nTOP 10 TRADES :")
    print(
        df.sort_values("PnL", ascending=False)
        .head(10)[columns_to_show]
        .to_string(index=False)
    )

    print("\nBOTTOM 10 TRADES :")
    print(
        df.sort_values("PnL", ascending=True)
        .head(10)[columns_to_show]
        .to_string(index=False)
    )


# ============================================================
# CONCENTRATION DES GAINS
# ============================================================

print("\n" + "=" * 70)
print("8. CONCENTRATION DU PNL")
print("=" * 70)

if "PnL" in df.columns:

    pnl_sorted = df.sort_values("PnL", ascending=False).reset_index(drop=True)

    total_pnl = pnl_sorted["PnL"].sum()

    if total_pnl != 0:

        for n in [5, 10, 20, 50, 100]:

            contribution = (
                pnl_sorted.head(n)["PnL"].sum()
                / total_pnl
            )

            print(
                f"Top {n:3d} trades = "
                f"{pct(contribution)} du PnL total"
            )


# ============================================================
# EQUITY CURVE PAR TRADE
# ============================================================

print("\n" + "=" * 70)
print("9. DRAWDOWN APPROXIMATIF")
print("=" * 70)

if "PnL" in df.columns:

    if "Exit_Date" in df.columns:
        equity_df = (
            df.sort_values("Exit_Date")
            .copy()
        )
    else:
        equity_df = df.copy()

    equity_df["Cumulative_PnL"] = equity_df["PnL"].cumsum()

    equity_df["Peak"] = (
        equity_df["Cumulative_PnL"]
        .cummax()
    )

    equity_df["Drawdown"] = (
        equity_df["Cumulative_PnL"]
        - equity_df["Peak"]
    )

    max_dd = equity_df["Drawdown"].min()

    print(f"\nDrawdown max approximatif : {money(max_dd)}")

    # Avec capital initial de $10,000
    initial_capital = 10000

    equity_df["Equity"] = (
        initial_capital
        + equity_df["Cumulative_PnL"]
    )

    equity_df["Equity_Peak"] = (
        equity_df["Equity"].cummax()
    )

    equity_df["DD_Pct"] = (
        equity_df["Equity"]
        / equity_df["Equity_Peak"]
        - 1
    )

    max_dd_pct = equity_df["DD_Pct"].min()

    print(
        f"Drawdown max approximatif % : "
        f"{pct(max_dd_pct)}"
    )


# ============================================================
# CONTROLE DES LOSERS A -2%
# ============================================================

print("\n" + "=" * 70)
print("10. CONTROLE DES LOSSES")
print("=" * 70)

if "Return" in df.columns:

    exact_sl = df[
        np.isclose(
            df["Return"],
            -0.02,
            atol=0.0005
        )
    ]

    print(
        f"\nTrades proches de -2% : "
        f"{len(exact_sl):,}"
    )

    print(
        f"Pourcentage des trades : "
        f"{pct(len(exact_sl) / len(df))}"
    )


# ============================================================
# CONCLUSION AUTOMATIQUE
# ============================================================

print("\n" + "=" * 70)
print("11. RESUME")
print("=" * 70)

if "PnL" in df.columns:

    winners = df[df["PnL"] > 0]
    losers = df[df["PnL"] < 0]

    gross_profit = winners["PnL"].sum()
    gross_loss = abs(losers["PnL"].sum())

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.inf
    )

    print(f"\nTrades          : {len(df):,}")
    print(f"Win rate        : {pct((df['PnL'] > 0).mean())}")
    print(f"PnL             : {money(df['PnL'].sum())}")
    print(f"Profit Factor   : {pf:.2f}")

    if "Exit_Date" in df.columns:
        years = sorted(df["Exit_Date"].dt.year.dropna().unique())
        print(f"Années          : {years}")

    print("\nIMPORTANT :")
    print(
        "Ce rapport sert à auditer le résultat du backtest. "
        "Il ne valide pas encore la stratégie."
    )

print("\n" + "=" * 70)
print("FIN DE L'AUTOPSIE")
print("=" * 70)