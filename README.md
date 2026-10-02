# Market Lab

Recherche sur actions US du snapshot **TOP100_US**. Les benchmarks V1 historiques
étaient LONG, sans connexion broker. Le Bot Core V1, décrit plus bas, ajoute
uniquement une connexion IBKR Paper pour le candidat swing V2 gelé.

## Benchmark final

Momentum V1, Mean Reversion V4.4 et Pullback V1-A ont été comparés sur
2018–2025, règles figées, mêmes coûts (0,20 % aller-retour) et même benchmark
portefeuille (10 000 USD, 10 % par entrée, cinq positions maximum).

**Verdict Top100 : DROP pour les trois.** Les moyennes nettes 3D deviennent
négatives après retrait des cinq meilleurs contributeurs. Aucune stratégie
n'est retenue pour déploiement à l'issue de cette mission. Pas de variante
créée pour sauver les résultats.

- [Décision et résultats](results/v1_final_benchmark/decision.md)
- [Règles exactes figées avant résultats](research/v1_benchmark/protocol.md)
- [Reproduction et tests](research/v1_benchmark/README.md)
- [Snapshot Top100 du 2 octobre 2026](data/universe/top100_us_v1.csv)
- [Sources et biais d'univers](data/universe/README.md)

## Organisation

| Périmètre actif | Emplacement |
|---|---|
| Univers unique figé | `data/universe/` |
| Comparaison des trois signaux historiques | `research/v1_benchmark/` |
| Primitives du moteur commun | `research/research_engine/` |
| Résultats synthétiques | `results/v1_final_benchmark/` |
| Recherches antérieures, conservées en place | [Index des archives](archive/README.md) |

Le snapshot actuel introduit un **survivorship bias historique accepté**.
99 sociétés ont un historique au moins partiel en 2018–2025 ; SPCX, cotée en
2026, reste dans l'univers sans observations fictives. Les historiques ajustés
Yahoo sont révisables. Ce benchmark rétrospectif n'est pas une validation OOS
indépendante et son sizing n'est pas celui du futur bot.

## Suites du benchmark V1

À l'issue du benchmark V1, aucune stratégie n'avait satisfait les critères
de passage. La recherche V2 et le Bot Core Paper ont ensuite été développés
séparément ; aucun passage au trading réel n'est prévu dans ce dépôt.

## Recherche V2 séparée

[Research Engine V2](research/research_v2/README.md) explore des signaux LONG
swing et intraday sur le même snapshot, avec gel avant validation. Le résultat
swing comporte un **KEEP CANDIDATE** et sept DROP ; l'intraday dispose seulement
d'un pilote technique de cinq séances, sans candidat. Ce candidat n'est pas
encore une stratégie déployable : les années 2024–2025 ont déjà été examinées
dans les recherches V1. [Décision et limites V2](results/research_v2/decision.md).

## Bot Core V1 — paper uniquement

Le [Bot Core V1](bot/README.md) charge le candidat swing V2 gelé et sépare
les signaux, le risque, l'état SQLite et l'adaptateur IBKR Paper. Les ordres
sont désactivés par défaut ; aucun trading réel n'est implémenté. Le contrôle
2026 et ses limites sont documentés dans
[Research V2 2026](results/research_v2_2026/decision.md).
