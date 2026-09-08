# Pullback Long V1-A — recherche clôturée

**Verdict : REJETER.** L'edge net est trop faible, instable et concentré,
notamment sur NVDA. La recherche V1-A est clôturée pour éviter l'overfitting :
aucune variante supplémentaire ne doit être créée pour sauver cette règle.

## Définition et méthode

A : `Close > SMA50`, `SMA20 > SMA50`, `Return_20D > 0`, `Return_3D < 0`.
La validation ne conserve que le premier signal de chaque épisode : passage
de A faux à A vrai pour le même ticker. Il faut ensuite un retour à A faux
avant un nouveau signal. Aucun état n'est réinitialisé aux frontières temporelles.

Signal à la clôture t, entrée à `Open[t+1]`, sortie à `Close[t+h]` :
`Future_Return_h = Close[t+h] / Open[t+1] - 1`. Positif = favorable au LONG.
Horizons : 1D, **3D principal**, 5D secondaire. Aucune optimisation.
Frais et slippage de 0,05 % chacun à chaque côté :
`Net_Return = (1 + Future_Return) * (0.9995**2 / 1.0005**2) - 1`.

Train 2018–2021, OOS rétrospectif 2022–2025. Walk-forward annuel 2021–2025,
avec les trois années précédentes comme train, sans recalibrage. Les sorties
au-delà de chaque fenêtre sont purgées par horizon. Les années OOS avaient
déjà été examinées dans l'étude initiale ; OOS et walk-forward se recouvrent.

## Résultats principaux

5 813 signaux, 47 tickers, 1 533 dates ; 8 037 observations répétées retirées.

| Période | Moyenne brute 3D | Moyenne nette 3D | Win rate net 3D |
|---|---:|---:|---:|
| Global | +0,2453 % | +0,0450 % | 50,75 % |
| Baseline global | +0,1590 % | −0,0411 % | 49,52 % |
| OOS | +0,2468 % | +0,0465 % | 50,04 % |
| Walk-forward, tests cumulés | +0,2466 % | +0,0463 % | 50,39 % |

Seulement 4/8 années positives nettes à 3D, et 2/5 années de test walk-forward.
Sans NVDA, la moyenne nette OOS devient −0,0044 %. Sans les trois meilleurs
contributeurs, la moyenne globale devient −0,0293 %. NVDA représente 74,5 %
de la contribution nette globale et 109,3 % de celle de l'OOS.
La fréquence est suffisante, mais pas la robustesse de l'avantage après coûts.

Les contributions supposent un même montant investi par signal, sans sizing
ni portefeuille simulé. Des épisodes distincts peuvent se chevaucher pendant
un hold ; un signal par épisode ne signifie pas une seule position par ticker.
Les contrôles intégrés vérifient la causalité, l'alignement t → Open[t+1],
la concordance avec le core et l'absence de double comptage des épisodes.

## Archives et reproduction

- `pullback_long_v1_research.py` : étude initiale A/B, sans coûts. B ajoutait
  l'absence de clôture sous sa SMA50 sur t−2, t−1 et t. Son diagnostic historique
  d'épisode utilisait les séquences de Return_3D négatif ; il est distinct de
  la définition A faux → vrai retenue pour la validation.
- `pullback_long_v1a_validation.py` : validation finale de A uniquement.
- `../../results/pullback/initial/` : effectifs, statistiques et synthèse initiale.
- `../../results/pullback/v1a_validation/` : statistiques globales, temporelles,
  annuelles, walk-forward et diagnostics de concentration/leave-one-stock-out.

Les CSV expriment les rendements et win rates en fractions décimales.
Les exports détaillés `observations.csv` et `signals.csv`, les caches OHLC
et les fichiers temporaires ne sont pas versionnés ; les scripts les régénèrent.

Données : core existant `results/short_momentum/short_momentum_v1_research_core.csv`,
93 107 observations du 22/01/2018 au 05/12/2025 (années extrêmes partielles).
Les empreintes du core et du cache OHLC sont conservées dans les synthèses JSON.
Fournir l'historique OHLC existant avec Date, Ticker, Open, High, Low, Close ;
un historique révisé peut produire des résultats différents.
Depuis la racine du dépôt, avec Python 3, pandas et NumPy :

```sh
python -B research/pullback/pullback_long_v1_research.py --ohlc-csv /chemin/yahoo_ohlc_2018_2025.csv --output-dir /tmp/pullback-initial
python -B research/pullback/pullback_long_v1a_validation.py --ohlc-csv /chemin/yahoo_ohlc_2018_2025.csv --output-dir /tmp/pullback-validation
```

Ne pas utiliser `python -O`, qui désactive les assertions de contrôle.
