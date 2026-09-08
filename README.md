# Market Lab

Laboratoire de recherche et de développement d'un système de trading algorithmique multi-stratégies.

Le projet a pour objectif de développer progressivement plusieurs stratégies de trading court terme, de les tester sérieusement sur des données historiques, puis de construire un portefeuille capable de combiner les stratégies les plus robustes.

> **Statut actuel :** recherche et backtesting
> **Trading réel :** pas encore activé

---

## 🎯 Objectif du projet

L'objectif final est de construire un système capable de :

1. Récupérer les données de marché
2. Analyser les actions
3. Détecter les opportunités
4. Évaluer la qualité des signaux
5. Sélectionner les meilleures opportunités
6. Déterminer la taille des positions
7. Exécuter les ordres
8. Gérer le risque
9. Fermer les positions
10. Analyser les résultats

L'objectif n'est pas de trouver une stratégie parfaite.

Nous voulons construire un ensemble d'environ **5 à 6 stratégies différentes**, capables de fonctionner dans des situations de marché différentes.

---

# 🧠 Architecture prévue

```text
Données de marché
       ↓
Analyse
       ↓
Détection des opportunités
       ↓
Score de confiance
       ↓
Sélection des opportunités
       ↓
Taille des positions
       ↓
Exécution
       ↓
Gestion du risque
       ↓
Sortie
       ↓
Analyse des résultats
```

La gestion globale du portefeuille et le sizing dynamique seront développés **après la création et la validation des différentes stratégies**.

---

# 📈 Les stratégies

## Stratégie 1 — Mean Reversion

### Concept

Chercher des actions ayant subi une baisse importante à court terme et présentant un potentiel de rebond.

```text
Baisse excessive
       ↓
Situation potentiellement survendue
       ↓
LONG
```

### Statut

🟠 **En cours de finalisation**

La stratégie a donné des résultats intéressants sur plusieurs actions et conditions.

Cependant, les tests walk-forward ne sont pas encore suffisamment robustes pour considérer cette stratégie comme définitivement validée.

Elle reste donc une stratégie de recherche prometteuse.

---

## Stratégie 2 — Momentum V1

### Concept

Chercher des actions qui sont déjà dans un mouvement haussier suffisamment fort et qui pourraient continuer leur progression à court terme.

L'objectif n'est pas simplement d'acheter une action qui a beaucoup monté.

Nous cherchons plutôt :

```text
Volatilité / amplitude élevée
          +
Momentum récent fort
          ↓
Continuation potentielle
          ↓
LONG
```

### Signal retenu

Momentum V1 utilise actuellement :

* ATR en pourcentage élevé
* Momentum positif sur 10 jours

Les seuils sont calculés à partir des **3 années précédentes** et recalculés régulièrement afin d'éviter d'utiliser des informations futures.

### Entrée

* Signal détecté à la clôture
* Entrée à l'ouverture du jour suivant

### Sortie

* Durée maximale : **3 jours**
* Pas de Stop Loss / Take Profit dans cette V1
* Sortie temporelle

### Benchmark actuel

* Capital de référence : 10 000 $
* Taille provisoire : 15 % du capital par position
* Maximum expérimental : 5 positions simultanées
* Long uniquement

⚠️ Les 15 % ne représentent **pas le sizing final du futur bot**.

Cette valeur sert uniquement de benchmark comparable entre les stratégies.

### Coûts simulés

* Frais achat : 0,05 %
* Frais vente : 0,05 %
* Slippage achat : 0,05 %
* Slippage vente : 0,05 %

Soit environ 0,20 % aller-retour.

### Recherche effectuée

Momentum V1 a notamment été testé avec :

* Analyse des facteurs
* ATR
* Momentum 10 jours
* Nombre de jours positifs
* Séquences de hausse
* Combinaisons de facteurs
* OOS
* Walk-forward
* Ranking
* Backtesting portefeuille
* Frais et slippage
* Concentration des performances
* Robustesse de l'univers
* Robustesse temporelle
* Régimes de marché

### Conclusion

🟢 **STRATÉGIE GELÉE**

Momentum V1 est suffisamment étudiée pour être conservée comme première stratégie de référence.

Nous ne cherchons plus à optimiser cette stratégie avant d'avoir développé les autres.

---

# 📉 Stratégie 3 — Short Momentum

### Concept

Créer le pendant baissier de Momentum.

Chercher des actions dont la baisse est actuellement suffisamment forte et active pour qu'une continuation baissière soit possible à court terme.

```text
Forte baisse active
        +
Momentum négatif
        +
Volatilité suffisante
        ↓
Continuation potentielle
        ↓
SHORT
```

Attention :

> Une action qui a énormément chuté n'est pas automatiquement une bonne opportunité de short.

Le but est de détecter une **baisse encore active**, et non de shorter une action déjà complètement massacrée.

### Recherche prévue

Nous étudierons notamment :

* Rendement 1 jour
* Rendement 3 jours
* Rendement 5 jours
* Rendement 10 jours
* Rendement 20 jours
* ATR
* Momentum négatif
* Accélération baissière
* Nombre de jours de baisse
* Séquences de baisse
* Contexte de marché
* OOS
* Walk-forward
* Backtesting portefeuille
* Frais et slippage

Les seuils seront déterminés par les données et non choisis arbitrairement.

### Statut

🔵 **Prochaine stratégie à développer**

---

# 🔮 Stratégies futures

L'objectif actuel est de développer environ **5 à 6 stratégies**.

Les stratégies suivantes sont des candidates potentielles :

### Stratégie 4 — Breakout

Détecter une sortie d'une période de consolidation pouvant annoncer le début d'un nouveau mouvement.

### Stratégie 5 — Pullback

Chercher une correction temporaire au sein d'une tendance existante, puis entrer lorsque la tendance reprend.

### Stratégie 6 — Reversal / Recovery

Chercher un retournement après une correction importante.

La liste définitive n'est pas encore figée.

Une stratégie pourra être abandonnée si les tests montrent qu'elle n'est pas suffisamment robuste.

---

# 💰 Construction du portefeuille

Le portefeuille global ne sera construit qu'après le développement des différentes stratégies.

Nous étudierons ensuite :

* Corrélation entre stratégies
* Allocation du capital
* Sizing dynamique
* Score de confiance
* Nombre dynamique de positions
* Exposition long / short
* Risque global
* Drawdown du portefeuille
* Diversification

Le nombre de positions ne sera pas fixé arbitrairement.

Il dépendra notamment :

* du capital disponible
* du risque
* de la qualité des opportunités
* de l'exposition actuelle
* de la corrélation entre positions

---

# 🧪 Méthode de recherche

## Pas de fuite d'information

Une stratégie ne doit utiliser que les informations disponibles au moment où le signal aurait réellement été généré.

---

## Tests hors échantillon

Les performances historiques seules ne suffisent pas.

Nous utilisons notamment :

* périodes d'entraînement
* périodes de test
* données hors échantillon
* walk-forward

---

## Lutte contre le surapprentissage

L'objectif n'est pas de maximiser artificiellement les performances historiques.

Nous privilégions :

* règles simples
* robustesse
* plusieurs périodes
* plusieurs actions
* walk-forward
* stabilité
* réalisme des coûts

---

# 📊 Univers de marché

La recherche actuelle utilise environ **47 actions**, avec SPY utilisé comme facteur de contexte de marché.

Cette taille volontairement limitée permet de valider les stratégies avant d'élargir progressivement l'univers.

Évolution envisagée :

```text
~47 actions
     ↓
~100
     ↓
~300
     ↓
500+
```

L'élargissement ne sera effectué qu'après validation suffisante des stratégies.

---

# ⚙️ Backtesting

Les backtests évaluent notamment :

* rendement
* taux de réussite
* profit factor
* gain moyen par trade
* fréquence des trades
* drawdown
* régularité annuelle
* régularité mensuelle
* concentration
* robustesse temporelle
* robustesse selon les actions
* robustesse selon les régimes de marché

Aucun indicateur seul ne suffit pour valider une stratégie.

---

# 🎯 Objectif de trading

Le système est destiné principalement au trading court terme :

* intraday à terme
* trades de 1 à quelques jours
* priorité aux opportunités de qualité

L'objectif à terme est d'atteindre environ **500 trades de qualité par an**.

Ce nombre est une cible et non une contrainte absolue.

Nous préférerons toujours moins de trades robustes à un grand nombre de trades médiocres.

---

# 🛡️ Gestion du risque

Le système final pourra intégrer :

* Stop Loss
* Take Profit
* Break-even
* Trailing Stop
* Sizing dynamique
* Limite de risque par position
* Limite de risque portefeuille
* Contrôle de l'exposition long / short

Le levier ne sera envisagé qu'après une validation approfondie sans levier et une phase de paper trading suffisamment longue.

---

# 📁 Organisation du projet

```text
market-lab/
│
├── backtesting/
│
├── strategies/
│   ├── mean_reversion/
│   └── momentum/
│
├── validation/
│   └── mean_reversion/
│
├── research/
│   ├── mean_reversion/
│   └── momentum/
│
├── results/
│   ├── mean_reversion/
│   └── momentum/
│
└── archive/
    └── mean_reversion/
```

---

# 🛠️ Technologies

* Python 3
* pandas
* NumPy
* yfinance
* Git
* GitHub
* VS Code
* GitHub Codespaces

---

# 🗺️ Feuille de route

## Phase 1 — Développement des stratégies

* [x] Recherche Mean Reversion
* [ ] Finalisation Mean Reversion
* [x] Développement Momentum V1
* [x] Validation Momentum V1
* [x] Robustesse Momentum V1
* [x] Gel Momentum V1
* [ ] Développement Short Momentum
* [ ] Stratégie 4
* [ ] Stratégie 5
* [ ] Stratégie 6 si nécessaire

## Phase 2 — Portefeuille

* [ ] Comparaison des stratégies
* [ ] Corrélations
* [ ] Combinaison des stratégies
* [ ] Score global
* [ ] Sizing dynamique
* [ ] Nombre dynamique de positions
* [ ] Gestion du risque global
* [ ] Contrôle du drawdown

## Phase 3 — Exécution

* [ ] Données intraday
* [ ] Modèle de spread
* [ ] Slippage plus réaliste
* [ ] Gestion des ordres
* [ ] Moteur d'exécution

## Phase 4 — Paper Trading

* [ ] Données de marché en temps réel
* [ ] Génération des signaux
* [ ] Ordres simulés
* [ ] Suivi du portefeuille
* [ ] Monitoring
* [ ] Validation prolongée

## Phase 5 — Trading réel

Uniquement après validation suffisante :

* [ ] Connexion à un broker
* [ ] Petit capital initial
* [ ] Limites de risque
* [ ] Surveillance
* [ ] Arrêt d'urgence
* [ ] Augmentation progressive du capital

---

# 📌 Statut actuel

### Première stratégie

**Mean Reversion — 🟠 en cours de finalisation**

### Deuxième stratégie

**Momentum V1 — 🟢 gelée**

### Prochaine étape

**Short Momentum — 🔵 à développer**

Le projet reste actuellement un laboratoire de recherche et de backtesting.

Il n'est pas encore prêt pour le trading réel.
