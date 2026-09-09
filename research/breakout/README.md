# Breakout Long V1 — recherche clôturée

Décision : **Breakout A et Breakout B sont rejetés**. Cette branche de
recherche est clôturée afin d'éviter l'overfitting. Aucune nouvelle variante
de Breakout V1 ne doit être créée pour tenter de sauver l'idée.

## Définitions testées

- **A — breakout simple** : `Close[t] > max(High[t-20:t-1])`. Le niveau de
  référence utilise strictement les 20 séances précédant le signal.
- **B — breakout avec compression** : toutes les conditions de A, avec
  `ATR_Pct_10D[t-1]` inférieur à sa médiane glissante sur les 60 séances
  allant de t-60 à t-1. L'ATR est la moyenne simple du True Range sur
  10 séances, divisée par Close, conformément au calcul utilisé dans le dépôt.

Le signal est observable à la clôture t. L'entrée est à `Open[t+1]` et la
sortie à `Close[t+h]`, avec :
`Future_Return_h = Close[t+h] / Open[t+1] - 1`.
Les horizons étudiés sont 1D, 3D et 5D. Aucun coût, filtre supplémentaire
ou optimisation de paramètre n'a été appliqué.

## Résultats principaux

| Groupe | Observations | Moyenne 1D | Moyenne 3D | Moyenne 5D |
|---|---:|---:|---:|---:|
| Baseline | 93 107 | +0,0228 % | +0,1590 % | +0,2962 % |
| A | 7 812 | -0,0240 % | +0,0501 % | +0,2088 % |
| B | 5 289 | -0,0141 % | +0,0653 % | +0,2629 % |

A et B sous-performent le baseline aux trois horizons, avant même les coûts.
À 3D, A dépasse le baseline de la même année dans 2 années sur 8 et B dans
1 année sur 8. La compression améliore légèrement les moyennes de A, sans
produire un avantage brut clair ni stable. La fréquence des signaux est
suffisante, mais leur qualité statistique ne justifie pas une validation.

## Fichiers conservés

- `breakout_long_v1_research.py` reconstruit les facteurs, applique A et B,
  contrôle la causalité et produit les résultats.
- `../../results/breakout/initial/statistics.csv` contient les statistiques
  globales et annuelles, avec les baselines.
- `../../results/breakout/initial/annual_counts.csv` contient les effectifs,
  tickers et dates par année.
- `../../results/breakout/initial/summary.json` conserve les effectifs,
  diagnostics d'épisodes, décomptes sans chevauchement et contrôles techniques.

Les rendements et win rates des CSV sont exprimés en fractions décimales.
L'export détaillé des observations, le cache OHLC et les fichiers temporaires
ne sont pas versionnés. Le script peut les régénérer depuis l'historique OHLC
existant contenant Date, Ticker, Open, High, Low et Close.

Les contrôles intégrés vérifient notamment que le breakout utilise seulement
t-20 à t-1, que la compression s'arrête à t-1, que les signaux passés sont
invariants aux changements futurs et que l'entrée est alignée sur Open[t+1].
