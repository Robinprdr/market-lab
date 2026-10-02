# Market Lab V1

Bot actions US court terme en préparation : **TOP100_US, LONG uniquement,
1 à 3 séances, trois stratégies maximum**. Signal à la clôture t, entrée à
Open[t+1], sortie Close[t+h]. Aucun trading réel ni connexion broker.

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

## Étapes prévues

Benchmark final → moteur portefeuille → paper trading IBKR → réel avec petit
capital, uniquement si des stratégies satisfont les critères de passage.
Cette mission s'arrête au benchmark ; les étapes suivantes ne sont pas lancées.

## Recherche V2 séparée

[Research Engine V2](research/research_v2/README.md) explore des signaux LONG
swing et intraday sur le même snapshot, avec gel avant validation. Le résultat
swing comporte un **KEEP CANDIDATE** et sept DROP ; l'intraday dispose seulement
d'un pilote technique de cinq séances, sans candidat. Ce candidat n'est pas
encore une stratégie déployable : les années 2024–2025 ont déjà été examinées
dans les recherches V1. [Décision et limites V2](results/research_v2/decision.md).
