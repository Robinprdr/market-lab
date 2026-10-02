# V1 — protocole figé avant résultats Top100

Figé le 2 octobre 2026 avant tout calcul de performance Top100. Aucun seuil
ne sera modifié après le benchmark. Les anciens scripts restent intacts.

## Signaux retenus

- **Momentum V1** : ATR14/Close ≥ Q80 et Return_10D ≥ Q80. ATR14 est la
  moyenne simple sur 14 séances du true range. Les deux quantiles sont
  mutualisés entre les titres de l'univers, calculés sur les trois années
  civiles précédentes et fixés pour l'année suivante. Pas de filtre ajouté.
  Source : `strategies/momentum/momentum_v1.py` et
  `research/momentum/momentum_v1_sizing_v5_1.py`.
- **Mean Reversion V4.4 Score5 + SMA50 ≥ 5 %** : rendement clôture/clôture
  1D entre −4 % et −2 % inclus ; Close > SMA50 ; Volume > moyenne20 Volume ;
  distance SMA20 entre 0 et 10 % inclus ; distance SMA50 entre 5 et 20 %
  inclus ; Return_3D < 0 ; abs(Return_1D)/(ATR14/Close) ≥ 1 ;
  rendement 1D de SPY > −2 %. Il s'agit des filtres existants, pas de nouveaux
  filtres du reboot. Source : `backtesting/backtest_v4.py` et
  `validation/mean_reversion/v44_portfolio_validation.py`.
- **Pullback V1-A** : Close > SMA50, SMA20 > SMA50, Return_20D > 0,
  Return_3D < 0. Premier signal de chaque épisode A faux → vrai uniquement,
  sans réinitialisation annuelle. Source : `research/pullback/README.md`.

Historique connu avant le reboot : Momentum, export portefeuille V5.1 3D,
872 trades, moyenne nette 1,1236 %, PF 1,6835, DD −23,94 %, rendement +531,24 %.
Ces chiffres anciens ne constituent pas une validation du nouveau benchmark.
Mean Reversion V4.4 retenue : 162 trades, PF 1,588, DD −4,51 %, rendement
+20,04 %, expectancy 12,37 USD ; 5/5 fenêtres positives dans V4.3 (119 trades).
La base avait PF 1,08 et DD −25,95 %, Score5 PF 1,228 et DD −7,88 %.
Le choix du filtre 5 % privilégie couverture et simplicité plutôt que le
filtre 7,5 % (62 trades/4 fenêtres) ou 10 % (20 trades/2 fenêtres).
Pullback : 5 813 signaux, moyenne nette 3D +0,0450 %, 4/8 années positives,
−0,0293 % sans ses trois meilleurs contributeurs ; précédemment rejetée.
Son réexamen identique sur Top100 est expressément demandé pour ce reboot.

## Conventions communes

2018–2025, années civiles complètes ; historique de chauffe depuis 2014.
Signal à Close[t], achat Open[t+1], vente Close[t+h], h ∈ {1,2,3}.
**3D reste l'horizon décisionnel**, 1D et 2D sont des comparaisons demandées,
pas un moyen de sélectionner après coup le meilleur holding.
Les anciens SL −2 %, TP +4 % et limite 5D de Mean Reversion sont remplacés
par ces sorties communes : nous comparons le signal existant, pas son ancien
portefeuille. Aucun SL/TP pour les autres stratégies.

OHLC Yahoo ajustés par AdjClose/Close, comme `auto_adjust=True` des anciens
scripts Momentum/Mean Reversion. Cela représente un historique ajusté des
distributions, pas des prix cash exécutables ; ajustements révisables et
survivorship bias du snapshot courant explicitement acceptés. Aucun comblement
de données absentes. SPY sert uniquement au filtre Mean Reversion existant et
au calendrier de séances. Les IPO récentes ne reçoivent aucun historique fictif.
Audit avant performances : début DELL au 28/12/2018 (classe C regular-way),
GEV au 02/04/2024 et SNDK au 24/02/2025 (exclusion when-issued).
DHR commence au 05/07/2016 : le facteur Yahoo AdjClose/Close saute de 55,55 %
ce jour-là et crée un faux rendement ajusté de +61,22 % lors du spin-off
Fortive. L'historique antérieur est inutilisé, sans inventer de facteur corrigé.
Sources et motifs dans `data_overrides.json`. Aucun de ces choix ne repose
sur une performance de stratégie. L'audit des grands sauts d'ajustement
identifie aussi KLAC/PGR en 2014 ; leurs prix ajustés restent continus.

Coûts communs sur le notional d'entrée : 0,05 % frais + 0,05 % slippage à
l'entrée, idem à la sortie. Net = Close_sortie/Open_entrée − 1 − 0,002,
conformément à `research_engine.execution_return`. Chaque côté est débité au
moment de l'opération. Ce modèle approximatif n'est pas un modèle de fills.

Portefeuilles séparés par stratégie/horizon : 10 000 USD, notional par entrée
= 10 % de l'equity à la clôture précédente, 5 positions maximum, une position
par ticker, fractions d'actions permises, aucun levier. Ordre alphabétique des
tickers pour départager les signaux simultanés, sans classement prédictif.
Les sorties du soir ne libèrent pas de place pour les entrées du matin.
Les signaux pendant une position sont ignorés, jamais mis en attente.
Évaluation quotidienne mark-to-market au Close ; drawdown depuis le capital
initial inclus. Aucun intérêt sur cash. Les trades non terminables avant
fin 2025 sont purgés selon le calendrier connu, pas selon leur rendement.

Les métriques portent sur les trades réellement acceptés par ce benchmark.
GROSS et NET utilisent les mêmes trades et quantités (allocation calculée
sur l'equity nette), afin d'isoler les coûts. Annualisation par 8 années,
contribution annuelle des trades selon l'année d'entrée ; rendements de
portefeuille annuels selon l'equity à chaque fin d'année.

## Décision et robustesse limitées

Trois diagnostics : année, ticker, retrait des cinq meilleurs contributeurs
en dollars nets puis nouveau passage du même portefeuille. Le retrait est un
stress test post-hoc, pas une nouvelle stratégie. Quantiles Momentum d'origine
conservés dans ce stress test pour ne pas changer le signal.

KEEP à 3D seulement si expectancy nette > 0, PF > 1, et moyenne nette reste
positive après retrait de la meilleure année (contribution USD), ainsi que
après retrait des cinq meilleurs tickers avec PF > 1 et portefeuille positif.
Un manque de trades empêche une conclusion positive. Sinon DROP.
Pas d'optimisation, pas de nouveaux filtres, pas de suite automatique.
