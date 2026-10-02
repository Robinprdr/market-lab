# Market Lab V1 — décision finale

Signaux existants figés avant résultats. Décision sur 3D ; aucun réglage après résultats.

| Stratégie | Verdict | Moyenne nette 3D | PF net | Sans meilleurs 5 tickers |
|---|---|---:|---:|---:|
| Momentum | DROP | 0.0294% | 1.016 | -0.1145% |
| MeanReversion | DROP | 0.1231% | 1.120 | -0.0874% |
| Pullback | DROP | 0.0085% | 1.007 | -0.0433% |

## Pourquoi ces décisions

- **Momentum — DROP** : 4/8 années à moyenne nette positive. Sans l'année la plus contributrice (2020), moyenne nette -0.0552%. Meilleurs contributeurs retirés : TSLA, SNDK, AMD, BA, ADI. Le stress test devient négatif : critère KEEP non rempli.
- **MeanReversion — DROP** : 4/8 années à moyenne nette positive. Sans l'année la plus contributrice (2023), moyenne nette 0.0168%. Meilleurs contributeurs retirés : META, ORCL, COP, DELL, C. Le stress test devient négatif : critère KEEP non rempli.
- **Pullback — DROP** : 4/8 années à moyenne nette positive. Sans l'année la plus contributrice (2020), moyenne nette -0.0357%. Meilleurs contributeurs retirés : AMD, META, APH, COP, AAPL. Le stress test devient négatif : critère KEEP non rempli.

## Comparaison complète

| Stratégie | Hold | Trades | Moy. brute | Moy. nette | PF net | DD net | Portefeuille net |
|---|---:|---:|---:|---:|---:|---:|---:|
| Momentum | 1D | 6435 | 0.0315% | -0.1685% | 0.831 | -68.21% | -67.63% |
| Momentum | 2D | 3467 | 0.1678% | -0.0322% | 0.978 | -27.42% | -15.91% |
| Momentum | 3D | 2414 | 0.2294% | 0.0294% | 1.016 | -26.52% | 0.17% |
| MeanReversion | 1D | 330 | 0.0734% | -0.1266% | 0.776 | -5.12% | -4.13% |
| MeanReversion | 2D | 328 | 0.3323% | 0.1323% | 1.168 | -3.29% | 4.27% |
| MeanReversion | 3D | 327 | 0.3231% | 0.1231% | 1.120 | -6.43% | 3.82% |
| Pullback | 1D | 7025 | 0.0093% | -0.1907% | 0.713 | -74.90% | -74.30% |
| Pullback | 2D | 4229 | 0.0946% | -0.1054% | 0.890 | -39.20% | -37.74% |
| Pullback | 3D | 2970 | 0.2085% | 0.0085% | 1.007 | -23.80% | -0.70% |

Détails : summary.csv (trades acceptés), annual.csv, ticker_contribution.csv,
portfolio_summary.csv ; audit.json conserve couverture, seuils annuels et empreintes.
Rendements en fractions décimales ; PnL en USD. Sans meilleurs 5 = nouveau passage
du portefeuille sans ces titres, pas un nouveau signal. Frais/slippage 0,20 % par trade.

## Limites

- Snapshot courant : survivorship bias accepté ; ce test est rétrospectif, pas OOS indépendant.
- 100 sociétés figées, 99 avec un historique au moins partiel en 2018–2025 ; SPCX cotée en 2026.
- IPO/spin-offs : fenêtres plus courtes, pas de données inventées avant cotation.
- DELL/GEV/SNDK limités à leur cotation regular-way ; DHR limité au segment après juillet 2016, avant calcul de performances.
- Yahoo ajusté des distributions, révisable ; résultats non garantis sur un téléchargement futur.
- Mean Reversion reprend le signal V4.4 mais utilise ici des sorties fixes sans SL/TP.
- 10 % par entrée et 5 positions sont un benchmark, pas le sizing final.
- Ordre alphabétique, entrées Open idéalisées, coûts constants ; capacité de marché non étudiée.

STOP : aucune nouvelle variante, aucun développement IBKR ou moteur portefeuille final.
