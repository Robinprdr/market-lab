# Gap Down Fade Long V1 — recherche clôturée

Décision : **REJETER**. Gap Down Fade Long V1 était une hypothèse
**exploratoire post-hoc**, formulée après avoir observé que Gap Down
Continuation ne produisait pas la continuation SHORT attendue. Les mêmes
données ont donc servi à générer puis à évaluer l'idée inverse ; cette étude
ne constitue pas une validation indépendante.

Gap Up Continuation, Gap Down Continuation et Gap Down Fade Long V1 sont
rejetés. La famille Gap est clôturée pour le moment. Aucune nouvelle variante
ne doit être créée afin d'éviter l'overfitting.

## Définition testée

`Gap[t] = Open[t] / Close[t-1] - 1`.

Signal LONG unique : `Gap[t] <= -2 %`. Le signal et l'entrée théorique sont à
`Open[t]`. Les rendements de l'action sont mesurés à `Close[t]` pour 1D,
`Close[t+2]` pour 3D et `Close[t+4]` pour 5D. Aucun autre seuil, coût,
slippage, filtre, sizing ou règle de sortie n'a été testé.

## Résultats principaux

3 011 signaux, 47 tickers et 818 dates. Gap moyen : -3,710 % ; médiane :
-2,873 %.

| Groupe | Moyenne 1D | Moyenne 3D | Moyenne 5D | Win rate 3D |
|---|---:|---:|---:|---:|
| Baseline LONG | +0,0245 % | +0,1644 % | +0,3043 % | 53,00 % |
| Gap Down Fade LONG | +0,0923 % | +0,1209 % | +0,3468 % | 52,24 % |

Le signal ne domine le baseline sur aucune combinaison cohérente de moyenne,
médiane et win rate. À 1D, l'avantage moyen disparaît sans 2018. À 3D, la
moyenne est inférieure au baseline et devient négative après retrait des trois
meilleurs contributeurs. À 5D, la moyenne est légèrement supérieure, mais le
win rate reste inférieur et l'avantage se concentre sur quelques titres.

## Concentration et rejet

- 2020 concentre 30,1 % des signaux et affiche une moyenne négative aux trois
  horizons.
- À 1D, 2018 représente 125,1 % de la contribution totale ; sans 2018, la
  moyenne devient -0,0253 %.
- À 3D, TSLA représente 64,7 % de la contribution. Sans TSLA, la moyenne tombe
  à +0,0460 % ; sans TSLA, NVDA et AMZN, elle devient -0,0276 %.
- À 5D, TSLA représente 26,9 % de la contribution et 2025 en représente 52,0 %.
- Seuls 25 tickers sur 47 ont une moyenne positive à 3D et à 5D.

L'exécution exactement à `Open[t]` est aussi optimiste : le gap devient connu
au moment où ce prix est établi. Les résultats étant déjà faibles et
concentrés avant coûts et slippage, aucune validation supplémentaire n'est
justifiée.

## Fichiers conservés

- `gap_down_fade_long_v1_research.py` : reproduction et contrôles de causalité.
- `../../results/gap_down_fade/initial/statistics.csv` : résultats globaux et
  annuels avec baseline LONG.
- `../../results/gap_down_fade/initial/annual_counts.csv` : fréquence et taille
  des gaps par année.
- `../../results/gap_down_fade/initial/ticker_concentration.csv` et
  `year_concentration.csv` : concentration par titre et année.
- `../../results/gap_down_fade/initial/summary.json` : synthèse, stress tests,
  signaux rapprochés et contrôles techniques.

Les rendements et win rates des CSV sont exprimés en fractions décimales.
Les signaux détaillés et le cache OHLC ne sont pas versionnés ; le script peut
les régénérer depuis l'historique OHLC existant.
