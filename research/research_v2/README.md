# Research Engine V2

Deux laboratoires LONG prix/volume : daily et intraday. Base locale réelle :
`5e2050afd8695b0e87e897b75731e623f15b507f`, branche de travail
`feature/research-engine-v2`. Aucun merge ni push implicite.

Le benchmark V1 reste conservé. La V2 autorise l'exploration bornée, puis
fige les candidats avant de lire leurs résultats de validation. **2024–2025
avait déjà été regardée dans les recherches antérieures** : séparation V2
stricte, mais pas une validation historiquement vierge.

## Méthode

`protocol.json` est écrit avant recherche : daily train 2018–2023, validation
2024–2025, horizons 1–10 séances. Warmup depuis les données disponibles avant
2018. Les quantiles sont ajustés uniquement dans le train (résultats train
in-sample), puis deviennent des seuils numériques fixes en validation.

Passage 1 : conditions individuelles, seuils Q20/Q50/Q80 train, deux sens.
Passages suivants : 24 features retenues, beam de 12 règles, combinaisons
jusqu'à 4 conditions incluant l'ancre de tendance. Limite de 10 000 variantes
par laboratoire. Classement moyenne nette pénalisée de 0,5 bp par condition
supplémentaire ; diversité des masques train (Jaccard ≤ 0,7). Jusqu'à huit
candidats, jamais une obligation de produire un résultat positif.

Ancre swing : SMA20 > SMA50 ; ancre intraday : Close > VWAP. Un trade par
ticker à la fois ; aucun plafond de fréquence, aucun ordre différé. Entrée
Open du bar suivant. Swing : sortie Close[t+h]. Intraday : holds 1/3/6/12
barres ou clôture de séance (horizon 0), plafonnés à la clôture effective.
Les sorties dynamiques ne sont pas lancées automatiquement : l'échantillon
n'a pas établi d'edge d'entrée suffisamment fiable.

Les features couvrent retours, accélération, distances SMA/EMA, ATR %, vol,
volumes relatifs/z-score, structure high/range, séquences, force relative et
SPY. Intraday ajoute VWAP, opening ranges, structure de séance, volume au même
créneau historique et contexte daily **strictement antérieur** à la séance.
Pas de backfill. Les barres sont horodatées au début ; le signal n'existe
qu'à `Bar_End`. Les 15m/30m sont supportées par l'agrégateur, non explorées ici.

Les sorties traversant la frontière train/validation sont purgées. Features
et warmup continuent, mais les positions commencent à zéro en validation.
Tous les candidats gelés sont évalués, sans reclassement ni retuning.
KEEP CANDIDATE exige les portes exactes de `protocol.json` ; il ne signifie
ni validation indépendante finale, ni mise en production.

Drawdown : PnL mark-to-market d'un notional fixe de 1/100 du capital initial
par ticker, pas de réinvestissement. Ce diagnostic n'est pas le portefeuille
final. PF et contributions : rendements à notional égal. Retrait des cinq
meilleurs contributeurs de la période comme stress post-hoc, pas comme filtre.

## Reproduction

Python 3.12 utilisé. Installer les versions de `requirements.txt` dans un
venv de travail, sans modifier les anciens scripts :

```sh
python -m pip install -r research/research_v2/requirements.txt
python -m unittest discover -s research -p 'test*.py'
python -m research.research_v2.run sample
python -m research.research_v2.run explore-swing
python -m research.research_v2.run explore-intraday
python -m research.research_v2.run freeze
python -m research.research_v2.run validate
```

Ces étapes initiales refusent de remplacer un freeze/une validation existante.
Les résultats de cette mission sont déjà versionnés : ne pas supprimer leur
verrou pour ajuster après observation. Les prix et caches locaux sont ignorés
par Git. Le daily se récupère au besoin avec le downloader V1 ; sa révision
peut différer des empreintes enregistrées.

Pour reproduire les candidats déjà gelés sans recherche ni modification des
résultats versionnés, utiliser la commande `reproduce` documentée dans le CLI.
Elle exigera les mêmes entrées et règles, et écrira dans un autre dossier.

Providers historiques : `sample --provider csv --csv-dir ... --start ...
--end ... --daily ...`, ou `--provider alpaca --feed sip` avec clés en variables
d'environnement, jamais en arguments ou dans Git. Le split 75/25 des séances
est persisté avant toute performance. Une nouvelle source historique exige
une expérience séparée, sans réutiliser le statut de vierge de dates déjà lues.

## Fichiers

- `features.py` : bibliothèque causale, features calculées une seule fois.
- `providers.py` : providers en lecture seule, calendrier et agrégation.
- `search.py` : simulation indépendante des positions par ticker, beam search.
- `run.py` : acquisition, exploration, freeze, validation et audits.
- `test_v2.py` : tests de causalité, coûts et contraintes de session.
- `data_sources.md` : disponibilité réelle et options de données.
- `results/research_v2/` : explorations complètes, candidats gelés, résultats,
  année/ticker/heure et décision lisible. Les explorations peuvent être volumineuses
  mais conservent toutes les variantes nécessaires à l'audit du multiple testing.

Pas de broker/live, de sizing final, de news, d'earnings, de SHORT ni de ML.
