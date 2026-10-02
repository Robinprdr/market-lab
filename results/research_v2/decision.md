# Research Engine V2 — exploration et validation séparées

**2024–2025 n’est pas historiquement vierge** : cette période a déjà été examinée en V1. Elle est strictement exclue de la sélection V2. Un KEEP reste un candidat, pas une validation finale indépendante.

## Exploration

Swing : 7520 variantes ; intraday : 1410 variantes. Les résultats train ne sont pas une preuve hors échantillon.
Gel : 2026-10-02T07:44:47.828617+00:00. Coûts swing 0,20 % ; intraday 0,09 % aller-retour, stress 0,18 %.

| Candidat | Laboratoire | Horizon | Trades train | Moyenne nette train | PF train |
|---|---|---:|---:|---:|---:|
| 489fb4ac218e | swing | 8 | 201 | 2.6868% | 2.413 |
| 0063ead074d8 | swing | 10 | 220 | 1.8835% | 1.913 |
| f78c4e441780 | swing | 10 | 369 | 1.7380% | 1.717 |
| 9db70f84ee51 | swing | 9 | 201 | 1.6920% | 1.632 |
| 8831b5f9c350 | swing | 10 | 242 | 1.6919% | 1.630 |
| 2366a81673c5 | swing | 9 | 235 | 1.5793% | 1.607 |
| 06a523fab176 | swing | 5 | 200 | 1.5341% | 1.643 |
| 1c585fde78e3 | swing | 8 | 202 | 1.4622% | 2.065 |

## Validation sans reconfiguration

| Candidat | Trades | Moyenne nette | PF net | DD diagnostic | Sans top5 | Décision |
|---|---:|---:|---:|---:|---:|---|
| 489fb4ac218e | 39 | 0.1013% | 1.030 | -1.00% | -1.3465% | DROP |
| 0063ead074d8 | 50 | 1.3066% | 1.560 | -0.70% | -0.8264% | DROP |
| f78c4e441780 | 149 | 1.5332% | 1.468 | -2.20% | -0.3821% | DROP |
| 9db70f84ee51 | 81 | 1.6801% | 1.599 | -1.00% | -0.4709% | DROP |
| 8831b5f9c350 | 83 | -0.3994% | 0.911 | -2.09% | -2.6762% | DROP |
| 2366a81673c5 | 94 | 1.6849% | 1.567 | -0.99% | 0.1258% | KEEP CANDIDATE |
| 06a523fab176 | 54 | 0.0168% | 1.006 | -0.79% | -2.6220% | DROP |
| 1c585fde78e3 | 66 | -0.0935% | 0.965 | -0.81% | -1.0986% | DROP |

Intraday réellement obtenu : 5 séances, 11706 lignes 1m, 5 actions + SPY. Essai technique seulement ; aucune conclusion de robustesse pluriannuelle.

## Limites

- Multiple testing : milliers de variantes, sans correction statistique conférant une preuve formelle ; train favorisé par sélection.
- Snapshot actuel : survivorship bias accepté ; historiques courts et corrections de données V1 conservés.
- Données daily ajustées Yahoo révisables ; coûts constants et fills Open/Close idéalisés.
- Drawdown : sleeves fixes 1/100 par ticker, mark-to-market, sans réinvestissement ; diagnostic, pas sizing final.
- Signal intraday au bar close, entrée bar suivant ; latence et spread réel non observés. VWAP Yahoo approximé depuis les minutes.
- Le rang intraday de cet échantillon porte sur cinq titres, pas sur les cent. Provider complet nécessaire avant étude de production.
- Aucun abonnement acheté, aucune clé disponible. Voir data_sources.md pour SIP historique et alternatives.
- Aucun réglage après validation. Aucun broker, ordre, levier ou moteur portefeuille final. STOP.
