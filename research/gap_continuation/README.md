# Gap Continuation V1 — recherche clôturée

Décision : **Gap Up continuation et Gap Down continuation sont rejetés**.
Gap Continuation V1 est clôturée. Aucune variante de continuation ne doit être
créée pour tenter de sauver cette idée et éviter l'overfitting.

## Définitions testées

Le gap est défini par `Gap[t] = Open[t] / Close[t-1] - 1`.

- **A — Gap Up continuation** : `Gap[t] >= +2 %`, direction LONG.
- **B — Gap Down continuation** : `Gap[t] <= -2 %`, direction SHORT.

Le signal et l'entrée théorique sont à `Open[t]`. Les rendements décrivent le
mouvement de l'action : 1D `Close[t] / Open[t] - 1`, 3D
`Close[t+2] / Open[t] - 1`, 5D `Close[t+4] / Open[t] - 1`.
Positif est favorable à A ; négatif est favorable à B. Aucun coût, filtre,
sizing ou ajustement du seuil fixé à 2 % n'a été appliqué.

## Résultats principaux

| Groupe | Observations | Moyenne 1D | Moyenne 3D | Moyenne 5D | Win rate directionnel 3D |
|---|---:|---:|---:|---:|---:|
| Baseline action | 93 953 | +0,0245 % | +0,1644 % | +0,3043 % | 53,00 % LONG / 46,86 % SHORT |
| A — Gap Up | 3 118 | +0,0702 % | +0,1845 % | +0,2661 % | 49,81 % |
| B — Gap Down | 3 011 | +0,0923 % | +0,1209 % | +0,3468 % | 47,69 % |

A présente une légère hausse de la moyenne à 1D et 3D, mais sa médiane 3D
est négative, son win rate 3D est inférieur à 50 %, et sa moyenne 5D reste
sous le baseline. Le résultat est sensible à 2020 et à quelques tickers :
sans AMD, la moyenne 3D retombe à +0,1302 %, sous le baseline.

Pour B, les rendements moyens de l'action sont positifs aux trois horizons,
donc défavorables à une continuation SHORT. Une moyenne favorable au SHORT
n'apparaît que dans 1 année sur 8 à 3D et à 5D. Les pertes directionnelles
restent négatives après retrait du meilleur ticker.

L'exécution exactement à `Open[t]` est optimiste en pratique, car le gap est
connu au moment où ce prix est établi. Les résultats étant déjà insuffisants
avant coûts et slippage, aucune validation supplémentaire n'est justifiée.

## Fichiers conservés

- `gap_continuation_v1_research.py` reconstruit les signaux et rendements,
  puis vérifie la causalité et l'alignement des horizons.
- `../../results/gap_continuation/initial/statistics.csv` contient les
  statistiques globales et annuelles avec les baselines LONG et SHORT.
- `../../results/gap_continuation/initial/annual_counts.csv` contient les
  effectifs, tickers, dates et tailles de gap par année.
- `../../results/gap_continuation/initial/ticker_concentration.csv` contient
  le diagnostic de concentration par ticker et horizon.
- `../../results/gap_continuation/initial/summary.json` conserve la synthèse,
  les épisodes rapprochés et les contrôles techniques.

Les rendements et win rates des CSV sont exprimés en fractions décimales.
L'export détaillé des observations et le cache OHLC ne sont pas versionnés ;
le script peut les régénérer depuis l'historique OHLC existant.
