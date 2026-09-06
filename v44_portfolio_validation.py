import pandas as pd
import numpy as np

import backtest_v4 as v4


# ============================================================
# V4.4 — VALIDATION PORTEFEUILLE
# ============================================================
#
# On utilise EXACTEMENT le moteur OHLC de V4.
#
# Comparaison :
#
# 1. BASE
# 2. SCORE 5
# 3. SCORE 5 + Distance SMA50 >= 5%
#
# Aucun changement au moteur :
# - entrée next Open
# - SL
# - TP
# - TIME
# - gaps
# - cash
# - max positions
# - mark-to-market
#
# ============================================================


def print_comparison(results):
    print()
    print("=" * 80)
    print("COMPARAISON V4.4")
    print("=" * 80)

    rows = []

    for name, result in results.items():

        if result is None:
            continue

        metrics_df, trades_df, equity_df = result

        if metrics_df is None or metrics_df.empty:
            continue

        m = metrics_df.iloc[0]

        rows.append({
            "Strategy": name,
            "Final": m["Final_Capital"],
            "Return": m["Total_Return"],
            "CAGR": m["CAGR"],
            "DD": m["Max_Drawdown"],
            "Sharpe": m["Sharpe"],
            "Trades": int(m["Trades"]),
            "WinRate": m["Win_Rate"],
            "PF": m["Profit_Factor"],
            "Expectancy": m["Expectancy"],
            "SPY": m["SPY_BuyHold"]
        })

    comparison = pd.DataFrame(rows)

    if comparison.empty:
        print("Aucun résultat.")
        return

    print()

    for _, row in comparison.iterrows():

        print(f"--- {row['Strategy']} ---")

        print(
            f"Capital final : "
            f"${row['Final']:,.2f}"
        )

        print(
            f"Performance   : "
            f"{row['Return'] * 100:.2f}%"
        )

        print(
            f"CAGR          : "
            f"{row['CAGR'] * 100:.2f}%"
        )

        print(
            f"Max Drawdown  : "
            f"{row['DD'] * 100:.2f}%"
        )

        print(
            f"Sharpe        : "
            f"{row['Sharpe']:.2f}"
        )

        print(
            f"Trades        : "
            f"{row['Trades']}"
        )

        print(
            f"Win Rate      : "
            f"{row['WinRate'] * 100:.2f}%"
        )

        print(
            f"Profit Factor : "
            f"{row['PF']:.2f}"
        )

        print(
            f"Expectancy    : "
            f"${row['Expectancy']:.2f}"
        )

        print()

    # --------------------------------------------------------
    # Tableau résumé
    # --------------------------------------------------------

    print("=" * 80)
    print("TABLEAU RÉSUMÉ")
    print("=" * 80)

    display = comparison.copy()

    display["Final"] = display["Final"].map(
        lambda x: f"${x:,.2f}"
    )

    display["Return"] = display["Return"].map(
        lambda x: f"{x * 100:.2f}%"
    )

    display["CAGR"] = display["CAGR"].map(
        lambda x: f"{x * 100:.2f}%"
    )

    display["DD"] = display["DD"].map(
        lambda x: f"{x * 100:.2f}%"
    )

    display["WinRate"] = display["WinRate"].map(
        lambda x: f"{x * 100:.2f}%"
    )

    display["SPY"] = display["SPY"].map(
        lambda x: f"{x * 100:.2f}%"
    )

    display["PF"] = display["PF"].map(
        lambda x: f"{x:.2f}"
    )

    display["Sharpe"] = display["Sharpe"].map(
        lambda x: f"{x:.2f}"
    )

    display["Expectancy"] = display["Expectancy"].map(
        lambda x: f"${x:.2f}"
    )

    print(
        display.to_string(index=False)
    )

    comparison.to_csv(
        "v44_portfolio_comparison.csv",
        index=False
    )

    print()
    print(
        "Fichier créé : "
        "v44_portfolio_comparison.csv"
    )


def main():

    print()
    print("=" * 80)
    print("V4.4 — PORTFOLIO VALIDATION")
    print("=" * 80)

    print()
    print("Cette version réutilise le moteur OHLC V4.")
    print()
    print("Stratégies testées :")
    print("  1. BASE")
    print("  2. SCORE5")
    print("  3. SCORE5 + SMA50 >= 5%")

    # ========================================================
    # 1. DONNÉES
    # ========================================================

    raw_data = v4.download_data()

    print()
    print("Calcul des indicateurs...")

    prepared = v4.prepare_data(
        raw_data
    )

    print(
        f"Données préparées : "
        f"{len(prepared)} tickers"
    )

    # ========================================================
    # 2. SIGNAUX
    # ========================================================

    print()
    print("Construction des signaux...")

    signals = v4.build_signals(
        prepared
    )

    print(
        f"Signaux de base : "
        f"{len(signals)}"
    )

    # ========================================================
    # 3. BASE
    # ========================================================

    print()
    print("=" * 80)
    print("TEST 1/3 — BASE")
    print("=" * 80)

    base_result = v4.run_portfolio_backtest(
        prepared,
        signals,
        "BASE",
        0
    )

    if base_result[0] is not None:

        v4.print_report(
            base_result[0],
            base_result[1],
            base_result[2]
        )

    # ========================================================
    # 4. SCORE 5
    # ========================================================

    print()
    print("=" * 80)
    print("TEST 2/3 — SCORE 5")
    print("=" * 80)

    score5_result = v4.run_portfolio_backtest(
        prepared,
        signals,
        "SCORE5",
        5
    )

    if score5_result[0] is not None:

        v4.print_report(
            score5_result[0],
            score5_result[1],
            score5_result[2]
        )

    # ========================================================
    # 5. SCORE 5 + SMA50 >= 5%
    # ========================================================

    print()
    print("=" * 80)
    print("TEST 3/3 — SCORE 5 + SMA50 >= 5%")
    print("=" * 80)

    # --------------------------------------------------------
    # On crée une copie.
    #
    # Les trades Score 5 qui sont sous SMA50 +5%
    # sont volontairement rétrogradés à Score 4.
    #
    # Ainsi le moteur V4, qui sélectionne Score >= 5,
    # ne prendra que :
    #
    # Score 5
    # ET
    # Distance SMA50 >= 5%
    # --------------------------------------------------------

    signals_sma50 = signals.copy()

    mask_remove = (
        (signals_sma50["Score"] == 5)
        & (
            signals_sma50["Distance_SMA50"]
            < 0.05
        )
    )

    removed = mask_remove.sum()

    signals_sma50.loc[
        mask_remove,
        "Score"
    ] = 4

    print()
    print(
        f"Trades Score 5 retirés par "
        f"le filtre SMA50 >= 5% : {removed}"
    )

    selected_final = signals_sma50[
        signals_sma50["Score"] >= 5
    ]

    print(
        f"Trades Score 5 restants : "
        f"{len(selected_final)}"
    )

    sma50_result = v4.run_portfolio_backtest(
        prepared,
        signals_sma50,
        "SCORE5_SMA50_5",
        5
    )

    if sma50_result[0] is not None:

        v4.print_report(
            sma50_result[0],
            sma50_result[1],
            sma50_result[2]
        )

    # ========================================================
    # 6. COMPARAISON
    # ========================================================

    results = {
        "BASE": base_result,
        "SCORE5": score5_result,
        "SCORE5_SMA50_5": sma50_result
    }

    print_comparison(
        results
    )

    # ========================================================
    # 7. ANALYSE AUTOMATIQUE
    # ========================================================

    print()
    print("=" * 80)
    print("ANALYSE V4.4")
    print("=" * 80)

    if (
        sma50_result[0] is not None
        and score5_result[0] is not None
    ):

        score5 = score5_result[0].iloc[0]
        sma = sma50_result[0].iloc[0]

        print()

        print(
            "SCORE5 -> "
            "SCORE5 + SMA50 >= 5%"
        )

        print(
            f"Win Rate : "
            f"{score5['Win_Rate'] * 100:.2f}% "
            f"-> "
            f"{sma['Win_Rate'] * 100:.2f}% "
            f"("
            f"{(sma['Win_Rate'] - score5['Win_Rate']) * 100:+.2f}pp)"
        )

        print(
            f"Profit Factor : "
            f"{score5['Profit_Factor']:.2f} "
            f"-> "
            f"{sma['Profit_Factor']:.2f}"
        )

        print(
            f"Drawdown : "
            f"{score5['Max_Drawdown'] * 100:.2f}% "
            f"-> "
            f"{sma['Max_Drawdown'] * 100:.2f}%"
        )

        print(
            f"Sharpe : "
            f"{score5['Sharpe']:.2f} "
            f"-> "
            f"{sma['Sharpe']:.2f}"
        )

        print(
            f"Trades : "
            f"{int(score5['Trades'])} "
            f"-> "
            f"{int(sma['Trades'])}"
        )

        print(
            f"Capital final : "
            f"${score5['Final_Capital']:,.2f} "
            f"-> "
            f"${sma['Final_Capital']:,.2f}"
        )

        print()

        # ----------------------------------------------------
        # Verdict indicatif
        # ----------------------------------------------------

        improvement_wr = (
            sma["Win_Rate"]
            > score5["Win_Rate"]
        )

        improvement_pf = (
            sma["Profit_Factor"]
            > score5["Profit_Factor"]
        )

        lower_dd = (
            abs(sma["Max_Drawdown"])
            < abs(score5["Max_Drawdown"])
        )

        better_sharpe = (
            sma["Sharpe"]
            > score5["Sharpe"]
        )

        better_return = (
            sma["Total_Return"]
            > score5["Total_Return"]
        )

        score = sum([
            improvement_wr,
            improvement_pf,
            lower_dd,
            better_sharpe,
            better_return
        ])

        print(
            f"Critères améliorés : "
            f"{score}/5"
        )

        print()

        if score >= 4:

            print(
                "🟢 SIGNAL TRÈS INTÉRESSANT"
            )

            print(
                "Le filtre SMA50 >= 5% "
                "semble améliorer la qualité "
                "du portefeuille."
            )

        elif score >= 3:

            print(
                "🟡 SIGNAL PROMETTEUR"
            )

            print(
                "Le filtre apporte des améliorations, "
                "mais nous devons regarder les chiffres "
                "plus précisément avant de le verrouiller."
            )

        else:

            print(
                "🔴 PAS D'AMÉLIORATION SUFFISANTE"
            )

            print(
                "Le filtre SMA50 >= 5% ne justifie "
                "pas encore son intégration."
            )

    print()
    print("=" * 80)
    print("V4.4 TERMINÉ")
    print("=" * 80)


if __name__ == "__main__":
    main()