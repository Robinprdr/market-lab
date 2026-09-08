import pandas as pd
import numpy as np
from pathlib import Path

DATA_FILE = Path("results/momentum/momentum_v1_research.csv")

INITIAL_CAPITAL = 10000.0
START_YEAR = 2022
END_YEAR = 2025

MAX_POSITIONS = 5
POSITION_PCT = 0.20

HOLD_DAYS = 3

FEE_BUY = 0.0005
FEE_SELL = 0.0005
SLIPPAGE_BUY = 0.0005
SLIPPAGE_SELL = 0.0005

# ============================================================
# UNIVERS À TESTER
# ============================================================

UNIVERSES = {
    "BASE_47": [],
    "SANS_TSLA": ["TSLA"],
    "SANS_AMD": ["AMD"],
    "SANS_NVDA": ["NVDA"],
    "SANS_AVGO": ["AVGO"],
    "SANS_TOP4": ["TSLA", "AMD", "NVDA", "AVGO"],
    "SANS_TOP5": ["TSLA", "AMD", "NVDA", "AVGO", "LLY"],
}

# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(DATA_FILE)

df["Date"] = pd.to_datetime(df["Date"])
df["Ticker"] = df["Ticker"].astype(str)

numeric_cols = [
    "Open",
    "Close",
    "ATR_Pct",
    "Return_10D",
]

for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(
    subset=["Date", "Ticker", "Open", "Close", "ATR_Pct", "Return_10D"]
).copy()

df = df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

# ============================================================
# SEUILS WALK-FORWARD
# ============================================================

thresholds = {}

for year in range(START_YEAR, END_YEAR + 1):

    train = df[df["Date"].dt.year < year]

    atr_threshold = train["ATR_Pct"].quantile(0.80)
    ret10_threshold = train["Return_10D"].quantile(0.80)

    thresholds[year] = {
        "ATR": atr_threshold,
        "Return10": ret10_threshold,
    }

    print(
        f"Threshold {year}: "
        f"ATR={atr_threshold:.6f} | "
        f"Return10={ret10_threshold:.6f}"
    )

# ============================================================
# BACKTEST
# ============================================================

def run_backtest(data, removed):

    universe = sorted(
        t for t in data["Ticker"].unique()
        if t not in removed
    )

    d = data[data["Ticker"].isin(universe)].copy()

    cash = INITIAL_CAPITAL
    positions = []
    trades = []

    equity_curve = []

    dates = sorted(
        d[
            (d["Date"].dt.year >= START_YEAR)
            & (d["Date"].dt.year <= END_YEAR)
        ]["Date"].unique()
    )

    for current_date in dates:

        today = d[d["Date"] == current_date]

        year = pd.Timestamp(current_date).year

        # ----------------------------------------------------
        # PRIX COURANTS
        # ----------------------------------------------------

        prices = dict(
            zip(today["Ticker"], today["Close"])
        )

        # ----------------------------------------------------
        # SORTIES
        # ----------------------------------------------------

        remaining = []

        for pos in positions:

            ticker = pos["Ticker"]

            if ticker not in prices:
                remaining.append(pos)
                continue

            current_price = prices[ticker]

            holding_days = (
                pd.Timestamp(current_date) - pos["Entry_Date"]
            ).days

            if holding_days >= HOLD_DAYS:

                exit_price = current_price

                effective_exit = (
                    exit_price
                    * (1 - SLIPPAGE_SELL)
                )

                proceeds = (
                    pos["Shares"]
                    * effective_exit
                    * (1 - FEE_SELL)
                )

                pnl = proceeds - pos["Cost_Basis"]

                trade_return = (
                    proceeds / pos["Cost_Basis"] - 1
                ) * 100

                cash += proceeds

                trades.append({
                    "Ticker": ticker,
                    "Entry_Date": pos["Entry_Date"],
                    "Exit_Date": pd.Timestamp(current_date),
                    "Return_pct": trade_return,
                    "PnL": pnl,
                    "Holding_Days": holding_days,
                })

            else:
                remaining.append(pos)

        positions = remaining

        # ----------------------------------------------------
        # EQUITY AVEC POSITIONS OUVERTES
        # ----------------------------------------------------

        equity = cash

        for pos in positions:

            ticker = pos["Ticker"]

            if ticker in prices:
                equity += (
                    pos["Shares"]
                    * prices[ticker]
                    * (1 - SLIPPAGE_SELL)
                )

        equity_curve.append({
            "Date": pd.Timestamp(current_date),
            "Equity": equity,
        })

        # ----------------------------------------------------
        # SIGNALS
        # ----------------------------------------------------

        if year not in thresholds:
            continue

        atr_threshold = thresholds[year]["ATR"]
        ret10_threshold = thresholds[year]["Return10"]

        candidates = today[
            (today["ATR_Pct"] >= atr_threshold)
            & (today["Return_10D"] >= ret10_threshold)
        ].copy()

        if candidates.empty:
            continue

        occupied = {p["Ticker"] for p in positions}

        candidates = candidates[
            ~candidates["Ticker"].isin(occupied)
        ]

        if candidates.empty:
            continue

        available_slots = MAX_POSITIONS - len(positions)

        if available_slots <= 0:
            continue

        # Classement déterministe :
        # ATR puis Return10
        candidates = candidates.sort_values(
            ["ATR_Pct", "Return_10D"],
            ascending=False
        )

        candidates = candidates.head(available_slots)

        # ----------------------------------------------------
        # ENTRÉES
        # ----------------------------------------------------

        for _, row in candidates.iterrows():

            if cash <= 0:
                break

            entry_price = row["Open"]

            effective_entry = (
                entry_price
                * (1 + SLIPPAGE_BUY)
            )

            # Taille = 20% de l'equity disponible
            current_equity = cash

            for pos in positions:

                ticker = pos["Ticker"]

                if ticker in prices:
                    current_equity += (
                        pos["Shares"]
                        * prices[ticker]
                    )

            allocation = min(
                current_equity * POSITION_PCT,
                cash
            )

            if allocation <= 0:
                continue

            cost_per_share = (
                effective_entry
                * (1 + FEE_BUY)
            )

            shares = allocation / cost_per_share

            total_cost = shares * cost_per_share

            if total_cost > cash:
                shares = cash / cost_per_share
                total_cost = shares * cost_per_share

            if shares <= 0:
                continue

            cash -= total_cost

            positions.append({
                "Ticker": row["Ticker"],
                "Entry_Date": pd.Timestamp(current_date),
                "Entry_Price": entry_price,
                "Shares": shares,
                "Cost_Basis": total_cost,
            })

    # ========================================================
    # LIQUIDATION FINALE
    # ========================================================

    if positions:

        last_date = dates[-1]

        last_data = d[d["Date"] == last_date]

        prices = dict(
            zip(last_data["Ticker"], last_data["Close"])
        )

        for pos in positions:

            ticker = pos["Ticker"]

            if ticker not in prices:
                continue

            exit_price = prices[ticker]

            effective_exit = (
                exit_price
                * (1 - SLIPPAGE_SELL)
            )

            proceeds = (
                pos["Shares"]
                * effective_exit
                * (1 - FEE_SELL)
            )

            pnl = proceeds - pos["Cost_Basis"]

            trade_return = (
                proceeds / pos["Cost_Basis"] - 1
            ) * 100

            holding_days = (
                pd.Timestamp(last_date)
                - pos["Entry_Date"]
            ).days

            cash += proceeds

            trades.append({
                "Ticker": ticker,
                "Entry_Date": pos["Entry_Date"],
                "Exit_Date": pd.Timestamp(last_date),
                "Return_pct": trade_return,
                "PnL": pnl,
                "Holding_Days": holding_days,
            })

    trades_df = pd.DataFrame(trades)

    if trades_df.empty:
        return {
            "Trades": 0,
            "PnL": 0,
            "Return_pct": 0,
            "Win_Rate": 0,
            "Profit_Factor": 0,
            "Max_DD": 0,
            "Final_Equity": INITIAL_CAPITAL,
        }

    total_pnl = trades_df["PnL"].sum()
    final_equity = INITIAL_CAPITAL + total_pnl

    win_rate = (
        trades_df["PnL"] > 0
    ).mean() * 100

    gross_profit = trades_df.loc[
        trades_df["PnL"] > 0,
        "PnL"
    ].sum()

    gross_loss = abs(
        trades_df.loc[
            trades_df["PnL"] < 0,
            "PnL"
        ].sum()
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else np.nan
    )

    eq = pd.DataFrame(equity_curve)

    if not eq.empty:

        eq["Peak"] = eq["Equity"].cummax()

        eq["Drawdown"] = (
            eq["Equity"] / eq["Peak"] - 1
        ) * 100

        max_dd = eq["Drawdown"].min()

    else:
        max_dd = 0

    return {
        "Trades": len(trades_df),
        "PnL": total_pnl,
        "Return_pct": total_pnl / INITIAL_CAPITAL * 100,
        "Win_Rate": win_rate,
        "Profit_Factor": pf,
        "Max_DD": max_dd,
        "Final_Equity": final_equity,
    }

# ============================================================
# EXECUTION DES 7 UNIVERS
# ============================================================

results = []

print("\n" + "=" * 90)
print("DÉBUT DES TESTS DE ROBUSTESSE")
print("=" * 90)

for name, removed in UNIVERSES.items():

    print("\n" + "-" * 90)
    print(f"TEST : {name}")

    if removed:
        print("Actions retirées :", ", ".join(removed))
    else:
        print("Actions retirées : aucune")

    result = run_backtest(df, removed)

    result["Universe"] = name
    result["Removed"] = ", ".join(removed) if removed else "NONE"

    results.append(result)

    print(f"Trades        : {result['Trades']}")
    print(f"PnL           : ${result['PnL']:,.2f}")
    print(f"Return        : {result['Return_pct']:.2f}%")
    print(f"Win Rate      : {result['Win_Rate']:.2f}%")
    print(f"Profit Factor : {result['Profit_Factor']:.2f}")
    print(f"Max DD        : {result['Max_DD']:.2f}%")
    print(f"Final Equity  : ${result['Final_Equity']:,.2f}")

# ============================================================
# TABLEAU FINAL
# ============================================================

results_df = pd.DataFrame(results)

results_df = results_df[
    [
        "Universe",
        "Removed",
        "Trades",
        "PnL",
        "Return_pct",
        "Win_Rate",
        "Profit_Factor",
        "Max_DD",
        "Final_Equity",
    ]
]

print("\n" + "=" * 90)
print("RÉSUMÉ FINAL - ROBUSTESSE DE L'UNIVERS")
print("=" * 90)

print(
    results_df.to_string(
        index=False,
        formatters={
            "PnL": lambda x: f"${x:,.2f}",
            "Return_pct": lambda x: f"{x:.2f}%",
            "Win_Rate": lambda x: f"{x:.2f}%",
            "Profit_Factor": lambda x: f"{x:.2f}",
            "Max_DD": lambda x: f"{x:.2f}%",
            "Final_Equity": lambda x: f"${x:,.2f}",
        }
    )
)

# ============================================================
# SAUVEGARDE
# ============================================================

output = Path(
    "results/momentum/momentum_v1_universe_robustness_3d.csv"
)

output.parent.mkdir(parents=True, exist_ok=True)

results_df.to_csv(output, index=False)

print("\n" + "=" * 90)
print("TEST TERMINÉ")
print("=" * 90)
print(f"Résultat sauvegardé dans : {output}")
