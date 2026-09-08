# Strategy 3 SHORT — recherche clôturée

Décision du 8 septembre 2026 : **recherche SHORT suspendue**.
Short Momentum V1 et V2, puis Bearish Failed Rally V1, V2 et V3 ont été
rejetés. Aucune nouvelle variante SHORT ne doit être créée. Ces fichiers
préservent les expériences terminées, sans chercher à les sauver par de
nouveaux filtres. L'objectif de cet arrêt est d'éviter l'overfitting.
Cette décision remplace le statut historique « à développer » du README racine.

## Définitions figées

Contexte commun à t−1 : Close < SMA50 et Return_10D < 0.

- **BFR V1 — cassure de structure** : séquence complète de 1 à 3 clôtures
  consécutives en hausse jusqu'à t−1 ; à t, clôture sous SMA50 et sous le
  minimum des Low de ces séances. Confirmation dès la séance suivante.
- **BFR V2 — rejet de SMA20** : Close[t−1] > Close[t−2], High[t] ≥ SMA20[t],
  Close[t] < SMA20[t] et Close[t] < Close[t−1].
- **BFR V3 — rejet intrajournalier** : Close[t−1] > Close[t−2],
  High[t] > High[t−1], Close[t] < Open[t], Close[t] < Close[t−1],
  (Close[t] − Low[t]) / (High[t] − Low[t]) ≤ 0,50. Range nul invalide.

Une seule définition par expérience, sans optimisation ni coûts.
Signal observable à la clôture t, entrée Open[t+1]. Horizons en séances :
**Future_Return_h = Close[t+h] / Open[t+1] − 1**.
Ce rendement décrit l'action : négatif = favorable au SHORT.

## Résultats et verdicts

| Expérience | Signaux | Moyenne action 1D | 3D | 5D | Verdict |
|---|---:|---:|---:|---:|---|
| Baseline | 93 107 | +0,0228 % | +0,1590 % | +0,2962 % | Référence |
| BFR V1 | 1 563 | +0,1894 % | +0,2366 % | +0,3647 % | REJETER |
| BFR V2 | 514 | +0,0873 % | +0,5133 % | +0,5437 % | REJETER |
| BFR V3 | 1 490 | +0,1502 % | +0,3402 % | +0,5484 % | REJETER |

Aucun avantage SHORT brut clair et raisonnablement stable. Les moyennes
globales restent positives aux trois horizons pour les trois expériences.
Les observations corrélées ne sont pas des trades indépendants.
**Strategy 3 SHORT est abandonnée pour le moment.**

## Archive des résultats

Dans [results/short_momentum/bearish_failed_rally](../../results/short_momentum/bearish_failed_rally/) :

- `statistics.csv` : moyennes, médianes et fractions négatives globales et
  annuelles, pour les trois versions et le baseline conservé une seule fois.
- `annual_counts.csv` : effectifs annuels, tickers et dates distincts par version.
- `summary.json` : provenance, contrôles, effectifs, verdicts et chevauchements.
- `signals_v1.csv`, `signals_v2.csv`, `signals_v3.csv` : signaux auditables,
  dates d'entrée/sortie et rendements ; environ 1,3 Mo au total.

Les nombres dans les CSV sont des fractions décimales, sauf les effectifs.
Le décompte des entrées sans chevauchement conserve le premier signal par
ticker puis ignore ceux dont l'entrée précède ou coïncide avec sa séance de
sortie à la clôture. Aucun plafond global de positions n'est simulé.
Les statistiques portent sur tous les signaux, pas sur un portefeuille filtré.

## Provenance et reproduction

Référence : commit `34f4bbb51d9e835d4a58800d54695980bb3bd19d` et CSV core
`results/short_momentum/short_momentum_v1_research_core.csv`.
Évaluation : 93 107 lignes, 47 tickers, du 22/01/2018 au 05/12/2025.
2018 et 2025 sont partielles. OHLC Yahoo Finance du 01/01/2018 au 20/12/2025
exclu, convention du script historique `auto_adjust=False`, sans Adj Close.
Les facteurs et rendements recalculés concordent avec le core à moins de
6 × 10⁻¹⁶. Les empreintes du core et de l'instantané OHLC sont dans `summary.json`.

Les scripts autonomes requièrent Python 3, pandas et NumPy. Pour reproduire
une expérience existante, depuis la racine du dépôt, par exemple :

```sh
python -B research/short_momentum/bearish_failed_rally_v1.py --cache-dir /tmp/market-lab-bfr-cache --output-dir /tmp/market-lab-bfr-v1
```

Les scripts V2/V3 s'utilisent de même avec leur numéro. `--ohlc-csv` permet
de fournir un historique existant (Date, Ticker, Open, High, Low, Close).
Sans cache, le script télécharge les données et vérifie leur concordance
avec le core figé. Yahoo peut réviser ses historiques : les résultats archivés
sont ceux de l'instantané testé, et un téléchargement ultérieur n'est pas
garanti identique. Les caches de prix, fichiers temporaires et rapports de
rapprochement redondants ne sont pas versionnés.

Les scripts gardent leurs sorties individuelles de reproduction ; les CSV
archivés ci-dessus regroupent les sorties validées sans dupliquer le baseline.
Les contrôles intégrés couvrent les bornes du signal, une implémentation
indépendante et l'invariance des signaux passés sur un historique tronqué.
V2/V3 contrôlent également la modification des prix futurs et l'alignement
positionnel entrée/sorties. Ne pas lancer Python avec `-O` : il désactive les assertions.
