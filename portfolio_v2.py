import pandas as pd
import numpy as np


# ============================================================
# PORTFOLIO V2
# ============================================================
#
# Objectif :
#
# Construire un backtest portefeuille réaliste à partir
# des trades déjà générés par notre moteur.
#
# On compare :
#
#   BASE      = tous les signaux
#   SCORE >=3
#   SCORE >=4
#   SCORE =5
#
# Le portefeuille possède :
#
#   - capital initial
#   - cash
#   - positions simultanées
#   - allocation fixe
#   - maximum de positions
#   - PnL réel en dollars
#   - equity quotidienne
#   - drawdown
#   - Profit Factor
#   - Expectancy
#   - Sharpe approximatif
#
# IMPORTANT :
# Ce script ne modifie PAS les règles du signal.
# Il sert à construire notre moteur de portefeuille.
#
# ============================================================


# ============================================================
# CONFIGURATION
# ============================================================

TRADES_FILE = "strategy_v1_scored_trades.csv"

INITIAL_CAPITAL = 10_000.0

ALLOCATION = 0.20

MAX_POSITIONS = 5

# On utilise le PnL déjà calculé par le backtester.
# PnL_Pct est exprimé sous forme décimale :
#
# +0.04 = +4%
# -0.02 = -2%


# ============================================================
# CHARGEMENT
# ============================================================

print("=" * 70)
print("PORTFOLIO V2")
print("=" * 70)

df = pd.read_csv(TRADES_FILE)

df["Date"] = pd.to_datetime(df["Date"])

# Date d'entrée
if "Entry_Date" in df.columns:
    df["Entry_Date"] = pd.to_datetime(df["Entry_Date"])

else:
    # Dans notre dataset actuel, Date correspond au signal.
    # Si Entry_Date n'existe pas, on utilise Date comme référence.
    df["Entry_Date"] = df["Date"]


# ============================================================
# VERIFICATION COLONNES
# ============================================================

required_columns = [
    "Ticker",
    "PnL_Pct",
    "Score",
]

missing = [
    col
    for col in required_columns
    if col not in df.columns
]

if missing:

    raise ValueError(
        "Colonnes manquantes : "
        + ", ".join(missing)
    )


# ============================================================
# NETTOYAGE
# ============================================================

df = df.dropna(
    subset=[
        "Ticker",
        "Entry_Date",
        "PnL_Pct",
        "Score",
    ]
).copy()

df = df.sort_values(
    ["Entry_Date", "Ticker"]
).reset_index(drop=True)


print(f"\nTrades disponibles : {len(df)}")

print(
    f"Capital initial : "
    f"${INITIAL_CAPITAL:,.2f}"
)

print(
    f"Allocation / position : "
    f"{ALLOCATION:.0%}"
)

print(
    f"Maximum positions : "
    f"{MAX_POSITIONS}"
)


# ============================================================
# PREPARATION DES DATES
# ============================================================

start_date = df["Entry_Date"].min()

end_date = df["Entry_Date"].max()

all_dates = pd.date_range(
    start=start_date,
    end=end_date,
    freq="D",
)


# ============================================================
# FONCTION DE BACKTEST
# ============================================================

def run_portfolio_backtest(
    trades,
    strategy_name,
):
    """
    Simule le portefeuille dans le temps.

    Important :
    le capital disponible est utilisé pour déterminer
    la taille des nouvelles positions.

    Une position consomme :

        equity * ALLOCATION

    jusqu'à MAX_POSITIONS simultanées.
    """

    trades = trades.copy()

    trades = trades.sort_values(
        ["Entry_Date", "Ticker"]
    ).reset_index(drop=True)

    cash = INITIAL_CAPITAL

    open_positions = []

    closed_trades = []

    equity_records = []

    # --------------------------------------------------------
    # Registre des positions
    # --------------------------------------------------------

    def position_value(position):

        return position["allocated_capital"] * (
            1 + position["pnl_pct"]
        )

    # --------------------------------------------------------
    # Simulation jour par jour
    # --------------------------------------------------------

    for current_date in all_dates:

        # ====================================================
        # 1. FERMER LES POSITIONS QUI DOIVENT ÊTRE FERMÉES
        # ====================================================

        remaining_positions = []

        for position in open_positions:

            if position["exit_date"] <= current_date:

                allocated = position[
                    "allocated_capital"
                ]

                pnl_dollars = (
                    allocated
                    * position["pnl_pct"]
                )

                cash += allocated + pnl_dollars

                position["exit_date_actual"] = current_date

                position["pnl_dollars"] = pnl_dollars

                closed_trades.append(position)

            else:

                remaining_positions.append(position)

        open_positions = remaining_positions


        # ====================================================
        # 2. NOUVEAUX SIGNAUX
        # ====================================================

        todays_trades = trades[
            trades["Entry_Date"] == current_date
        ]

        # ----------------------------------------------------
        # Trier par score décroissant.
        #
        # À score égal :
        # meilleur PnL historique connu n'est PAS utilisé.
        #
        # On utilise simplement l'ordre ticker.
        # ----------------------------------------------------

        todays_trades = todays_trades.sort_values(
            ["Score", "Ticker"],
            ascending=[False, True],
        )


        # ====================================================
        # 3. OUVERTURE DES POSITIONS
        # ====================================================

        for _, trade in todays_trades.iterrows():

            # -----------------------------------------------
            # Limite de positions
            # -----------------------------------------------

            if len(open_positions) >= MAX_POSITIONS:
                break

            # -----------------------------------------------
            # Éviter deux positions sur le même ticker
            # -----------------------------------------------

            ticker = trade["Ticker"]

            already_open = any(
                position["Ticker"] == ticker
                for position in open_positions
            )

            if already_open:
                continue

            # -----------------------------------------------
            # Capital disponible
            # -----------------------------------------------

            if cash <= 0:
                break

            # -----------------------------------------------
            # Taille de position
            # -----------------------------------------------

            current_equity = (
                cash
                + sum(
                    position["allocated_capital"]
                    for position in open_positions
                )
            )

            allocated_capital = (
                current_equity
                * ALLOCATION
            )

            allocated_capital = min(
                allocated_capital,
                cash,
            )

            if allocated_capital <= 0:
                continue

            # -----------------------------------------------
            # Date de sortie
            # -----------------------------------------------

            if "Exit_Date" in trade.index:

                exit_date = pd.to_datetime(
                    trade["Exit_Date"]
                )

            else:

                # Fallback :
                # on utilise Holding_Days si disponible.
                if "Holding_Days" in trade.index:

                    holding_days = int(
                        trade["Holding_Days"]
                    )

                else:

                    holding_days = 5

                exit_date = (
                    current_date
                    + pd.Timedelta(
                        days=holding_days
                    )
                )

            # -----------------------------------------------
            # Création position
            # -----------------------------------------------

            position = {
                "Ticker": ticker,

                "Signal_Date": trade["Date"],

                "Entry_Date": current_date,

                "exit_date": exit_date,

                "allocated_capital":
                    allocated_capital,

                "pnl_pct":
                    float(trade["PnL_Pct"]),

                "Score":
                    int(trade["Score"]),

                "Score_Level":
                    trade.get(
                        "Score_Level",
                        "",
                    ),

                "Exit":
                    trade.get(
                        "Exit",
                        "",
                    ),
            }

            # -----------------------------------------------
            # Débit du cash
            # -----------------------------------------------

            cash -= allocated_capital

            open_positions.append(position)


        # ====================================================
        # 4. CALCUL EQUITY
        # ====================================================

        open_value = sum(
            position_value(position)
            for position in open_positions
        )

        equity = cash + open_value

        equity_records.append(
            {
                "Date": current_date,
                "Strategy": strategy_name,
                "Cash": cash,
                "Open_Position_Value": open_value,
                "Open_Positions":
                    len(open_positions),
                "Equity": equity,
            }
        )


    # ========================================================
    # 5. FERMETURE FORCÉE EN FIN DE BACKTEST
    # ========================================================

    for position in open_positions:

        allocated = position[
            "allocated_capital"
        ]

        pnl_dollars = (
            allocated
            * position["pnl_pct"]
        )

        cash += allocated + pnl_dollars

        position["exit_date_actual"] = end_date

        position["pnl_dollars"] = pnl_dollars

        closed_trades.append(position)


    # ========================================================
    # DATAFRAME EQUITY
    # ========================================================

    equity_df = pd.DataFrame(
        equity_records
    )

    if equity_df.empty:

        return {
            "strategy": strategy_name,
            "trades": pd.DataFrame(),
            "equity": pd.DataFrame(),
            "metrics": {},
        }


    # --------------------------------------------------------
    # Corriger la dernière equity avec les positions
    # --------------------------------------------------------

    final_equity = cash

    equity_df.loc[
        equity_df.index[-1],
        "Equity"
    ] = final_equity


    # ========================================================
    # DRAWDOWN
    # ========================================================

    equity_df["Peak"] = (
        equity_df["Equity"]
        .cummax()
    )

    equity_df["Drawdown"] = (
        equity_df["Equity"]
        / equity_df["Peak"]
        - 1
    )

    max_drawdown = (
        equity_df["Drawdown"]
        .min()
    )


    # ========================================================
    # TRADES
    # ========================================================

    closed_df = pd.DataFrame(
        closed_trades
    )

    if closed_df.empty:

        return {
            "strategy": strategy_name,
            "trades": closed_df,
            "equity": equity_df,
            "metrics": {},
        }


    pnl_dollars = (
        closed_df["pnl_dollars"]
    )

    winners = pnl_dollars[
        pnl_dollars > 0
    ]

    losers = pnl_dollars[
        pnl_dollars < 0
    ]


    # ========================================================
    # METRIQUES
    # ========================================================

    total_trades = len(
        closed_df
    )

    win_rate = (
        len(winners)
        / total_trades
    )

    avg_pnl_pct = (
        closed_df["pnl_pct"]
        .mean()
    )

    median_pnl_pct = (
        closed_df["pnl_pct"]
        .median()
    )

    total_pnl_dollars = (
        pnl_dollars.sum()
    )

    profit_factor = np.nan

    if len(losers) > 0:

        profit_factor = (
            winners.sum()
            / abs(losers.sum())
        )


    # --------------------------------------------------------
    # Expectancy
    # --------------------------------------------------------

    avg_win = (
        winners.mean()
        if len(winners) > 0
        else 0
    )

    avg_loss = (
        losers.mean()
        if len(losers) > 0
        else 0
    )

    expectancy_dollars = (
        win_rate * avg_win
        + (1 - win_rate) * avg_loss
    )


    # ========================================================
    # SHARPE APPROXIMATIF
    # ========================================================

    equity_df["Daily_Return"] = (
        equity_df["Equity"]
        .pct_change()
        .replace(
            [np.inf, -np.inf],
            np.nan,
        )
        .fillna(0)
    )

    daily_std = (
        equity_df["Daily_Return"]
        .std()
    )

    if daily_std > 0:

        sharpe = (
            equity_df["Daily_Return"].mean()
            / daily_std
            * np.sqrt(252)
        )

    else:

        sharpe = np.nan


    # ========================================================
    # CAPITAL FINAL
    # ========================================================

    final_equity = equity_df[
        "Equity"
    ].iloc[-1]

    total_return = (
        final_equity
        / INITIAL_CAPITAL
        - 1
    )


    # ========================================================
    # METRICS
    # ========================================================

    metrics = {

        "Strategy":
            strategy_name,

        "Initial_Capital":
            INITIAL_CAPITAL,

        "Final_Equity":
            final_equity,

        "Total_Return":
            total_return,

        "Total_PnL_Dollars":
            total_pnl_dollars,

        "Trades":
            total_trades,

        "Win_Rate":
            win_rate,

        "Avg_PnL_Pct":
            avg_pnl_pct,

        "Median_PnL_Pct":
            median_pnl_pct,

        "Profit_Factor":
            profit_factor,

        "Expectancy_Dollars":
            expectancy_dollars,

        "Max_Drawdown":
            max_drawdown,

        "Sharpe":
            sharpe,
    }


    return {
        "strategy": strategy_name,
        "trades": closed_df,
        "equity": equity_df,
        "metrics": metrics,
    }


# ============================================================
# STRATEGIES À COMPARER
# ============================================================

strategies = {

    "BASE": df,

    "SCORE_3": df[
        df["Score"] >= 3
    ].copy(),

    "SCORE_4": df[
        df["Score"] >= 4
    ].copy(),

    "SCORE_5": df[
        df["Score"] == 5
    ].copy(),
}


# ============================================================
# BACKTEST
# ============================================================

all_metrics = []

all_equity = []

all_trades = []


for strategy_name, strategy_df in strategies.items():

    print("\n")
    print("=" * 70)
    print(
        f"BACKTEST : {strategy_name}"
    )
    print("=" * 70)

    print(
        f"Signaux disponibles : "
        f"{len(strategy_df)}"
    )

    result = run_portfolio_backtest(
        strategy_df,
        strategy_name,
    )

    metrics = result["metrics"]

    if not metrics:

        print("Aucun résultat.")

        continue


    all_metrics.append(metrics)

    equity_df = result["equity"]

    trades_df = result["trades"]

    equity_df.to_csv(
        f"equity_{strategy_name}.csv",
        index=False,
    )

    trades_df.to_csv(
        f"portfolio_trades_{strategy_name}.csv",
        index=False,
    )

    all_equity.append(
        equity_df
    )

    all_trades.append(
        trades_df
    )


    # ========================================================
    # AFFICHAGE
    # ========================================================

    print(
        f"\nCapital final : "
        f"${metrics['Final_Equity']:,.2f}"
    )

    print(
        f"Rendement total : "
        f"{metrics['Total_Return']:.2%}"
    )

    print(
        f"Trades : "
        f"{metrics['Trades']}"
    )

    print(
        f"Win rate : "
        f"{metrics['Win_Rate']:.1%}"
    )

    print(
        f"PnL moyen : "
        f"{metrics['Avg_PnL_Pct']:.3%}"
    )

    print(
        f"Médiane : "
        f"{metrics['Median_PnL_Pct']:.3%}"
    )

    print(
        f"Profit Factor : "
        f"{metrics['Profit_Factor']:.2f}"
        if not pd.isna(
            metrics["Profit_Factor"]
        )
        else "Profit Factor : N/A"
    )

    print(
        f"Expectancy : "
        f"${metrics['Expectancy_Dollars']:.2f}"
    )

    print(
        f"Max Drawdown : "
        f"{metrics['Max_Drawdown']:.2%}"
    )

    print(
        f"Sharpe : "
        f"{metrics['Sharpe']:.2f}"
        if not pd.isna(
            metrics["Sharpe"]
        )
        else "Sharpe : N/A"
    )


# ============================================================
# COMPARAISON FINALE
# ============================================================

metrics_df = pd.DataFrame(
    all_metrics
)

print("\n")
print("=" * 70)
print("COMPARAISON FINALE")
print("=" * 70)


for _, row in metrics_df.iterrows():

    print(
        f"\n{row['Strategy']}"
    )

    print(
        f"  Final equity : "
        f"${row['Final_Equity']:,.2f}"
    )

    print(
        f"  Return       : "
        f"{row['Total_Return']:.2%}"
    )

    print(
        f"  Trades       : "
        f"{int(row['Trades'])}"
    )

    print(
        f"  Win rate     : "
        f"{row['Win_Rate']:.1%}"
    )

    print(
        f"  Profit Factor: "
        f"{row['Profit_Factor']:.2f}"
    )

    print(
        f"  Expectancy   : "
        f"${row['Expectancy_Dollars']:.2f}"
    )

    print(
        f"  Max DD       : "
        f"{row['Max_Drawdown']:.2%}"
    )

    print(
        f"  Sharpe       : "
        f"{row['Sharpe']:.2f}"
    )


# ============================================================
# EXPORT GLOBAL
# ============================================================

metrics_df.to_csv(
    "portfolio_v2_metrics.csv",
    index=False,
)


if all_equity:

    combined_equity = pd.concat(
        all_equity,
        ignore_index=True,
    )

    combined_equity.to_csv(
        "portfolio_v2_equity.csv",
        index=False,
    )


if all_trades:

    combined_trades = pd.concat(
        all_trades,
        ignore_index=True,
    )

    combined_trades.to_csv(
        "portfolio_v2_trades.csv",
        index=False,
    )


# ============================================================
# FIN
# ============================================================

print("\n")
print("=" * 70)
print("FICHIERS CRÉÉS")
print("=" * 70)

print("✓ portfolio_v2_metrics.csv")
print("✓ portfolio_v2_equity.csv")
print("✓ portfolio_v2_trades.csv")

print("\n")
print("Backtest portefeuille terminé.")