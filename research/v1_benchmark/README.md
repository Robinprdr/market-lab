# Benchmark final V1

Trois signaux historiques, aucun nouveau seuil. Lire [le protocole figé](protocol.md)
pour les règles exactes, leur sélection et leurs performances précédentes.
`frozen_inputs.json` verrouille les empreintes du protocole, de l'univers et
des exceptions de données avant le premier calcul de performance Top100.

## Reproduction

Depuis la racine du dépôt, Python 3.11+ avec pandas 2.2.3 et NumPy 2.3.5
(versions utilisées pour l'export) :

```sh
python -m pip install pandas==2.2.3 numpy==2.3.5
python -m research.v1_benchmark.download_prices
python -m research.v1_benchmark.run_benchmark
python -m unittest discover -s research -p 'test*.py'
```

Le téléchargement réutilise les réponses JSON locales de `data/cache/v1_top100/`,
jamais le classement des capitalisations. Aucun secret/API payante nécessaire.
Les prix et réponses JSON volumineuses restent hors Git. Conserver ce cache
pour une reproduction numérique exacte : Yahoo peut réviser son historique.
Le manifeste local et l'audit versionné permettent de vérifier les empreintes.
Une nouvelle collecte peut différer ; ce n'est pas une permission de retoucher
les règles ni d'écraser silencieusement les décisions après optimisation.

Les sorties sont dans `results/v1_final_benchmark/` : quatre CSV compacts,
`audit.json` et `decision.md`. Un autre dossier de sortie peut être demandé
avec `--output /chemin/verification`, et un cache fourni avec `--prices`.

## Lecture

- `summary.csv` : 9 comparaisons de base et les 9 stress tests sans les
  cinq meilleurs tickers. Tous les rendements sont en fractions décimales.
  Le PF est le ratio gains/pertes des rendements par trade, non des dollars.
- `annual.csv` : statistiques des trades par année d'entrée ; rendement
  portefeuille mesuré entre equities de fin d'année, donc attribution
  différente pour les rares positions chevauchant le Nouvel An.
- `ticker_contribution.csv` : contribution USD et statistiques de chaque
  titre ayant des trades, portefeuille de base seulement.
- `portfolio_summary.csv` : performance et DD mark-to-market, gross/net.
- `audit.json` : couverture, seuils annuels Momentum, empreintes, décision.

GROSS utilise les mêmes trades/quantités que NET ; c'est le coût isolé du
même portefeuille, pas une seconde simulation avec réinvestissement sans frais.
Entrées théoriques à l'Open, sorties au Close ; le montant alloué utilise
l'equity de la clôture précédente. Les nouvelles positions ne bénéficient
jamais du produit d'une vente qui n'arrivera que le soir.

Le contrôle de causalité perturbe les prix futurs et vérifie que les signaux
antérieurs restent identiques. Les tests couvrent aussi les épisodes Pullback,
les sorties 1/2/3 séances, la saturation des positions, le drawdown non réalisé,
les frais, les réconciliations de cash et les années.

Ce code est un ledger de comparaison, pas le moteur portefeuille final du bot.
La mission s'arrête à la décision, sans nouveau filtre ni développement IBKR.
