# Production readiness — audit du 14 octobre 2026

Base : `feature/oracle-cloud-deployment-v1`, `417edabb170f06e15455b7a8d0870330e011e6ca`.
Branche de correction : `feature/production-readiness-audit`.

**Verdict : préparation locale adaptée à un pilote Oracle DRY_RUN supervisé ;
PAPER autonome plusieurs semaines non validé et non activé.**
Aucun accès IBKR réel, aucun message Telegram réel, aucun ordre, aucun déploiement ou achat
pendant cet audit. La base Paper existante est conservée intacte. Aucun seuil, filtre,
sizing, horizon, univers ou fichier de stratégie gelée modifié.

## Ce qui est intégré et prêt localement

Les correctifs ne sont pas perdus entre branches :

| Ancêtre intégré | Preuve dans le code |
|---|---|
| `f18aa53` cash multi-devise | `account_cash.py`, solde USD réel séparé de la devise de base, refus de conversion implicite |
| `0d09c93` phases déconnectées | `auction_checkpoints.py`, identités d'ordre, persistance, contrôle position avant MOC, absence de resoumission aveugle |
| `f3fe17e` preuves d'enchère et fuseaux | `execution_time.py`, conversion explicite ET/UTC, sessions NYSE, refus d'heure implicite/ambiguë |
| `f3fe17e` completedOrder quantité zéro | quantité totale d'ordre distincte de la quantité d'exécution ; seuls les fills confirmés modifient les positions |
| `f3fe17e` MOC Paper précoce | `CLOSED_WITH_TIMING_WARNING`, exécution confirmée mais précision temporelle non garantie ; fenêtre inchangée |
| `5a47cd1` Telegram/operations | commandes privées autorisées, kill switch SQLite, verrou de soumission, outbox et dashboard |

Les preuves détaillées permId/types/horodatages des enchères sont dans le workflow de
validation isolé. Le broker générique n'est pas pour autant un contrôleur autonome complet.
Le contrôle cash, la réconciliation fail-closed, les identifiants uniques et l'interdiction LIVE restent présents.

Le scheduler livré pour le serveur est `python -m bot.cloud`, pas la commande historique
`bot.operations`. Les wrappers cloud refusent PAPER/trading activé, exigent une base isolée,
refusent l'historique broker et empêchent un double scheduler. Ils ne construisent pas d'adaptateur IBKR.

## Ordonnancement réellement observé

| Étape | Séance normale ET | Ce que fait le cloud actuel |
|---|---|---|
| cohérence | 07:30 | réconciliation du ledger simulé uniquement |
| pré-ouverture | 09:15, avant 09:25 | vérifie le plan précédent et la cohérence, expose les intentions ; aucune transmission |
| sorties | 14:30 | vérifie la cohérence et les sorties prévues ; aucune transmission MOC |
| data | 16:30 | lit des séances complètes, constate Open/Close simulés |
| signal | 16:45 | règles Swing V2 gelées, intentions pour la prochaine séance NYSE |

Entrée simulée au prochain Open, sous le cap LOO inchangé ; si Open dépasse le cap,
`SIMULATED_NO_FILL`, aucune position ni sortie inventée. Sortie simulée au Close de la
**9e séance**, comptée depuis l'entrée incluse. Weekends/fériés exclus. Les demi-séances
utilisent leur vrai close : sorties 11:30, data 13:30, stratégie 13:45 ET.
Les instants sont timezone-aware ; DST testée. Les fills simulés sont constatés après
clôture, dans des tables séparées, sans prétendre à une exécution à l'enchère en temps réel.

## Bugs reproduits et corrections ciblées

Huit reproductions échouaient avant leur correction, avec ces défauts :

1. Une notification malformée/indisponible bloquait la lecture Telegram, donc `/kill`.
   Les commandes passent avant la livraison ; une réponse impossible ne bloque plus le
   `/kill` suivant. Si une commande n'a pas pu être appliquée, son offset n'est pas avancé.
2. Une notification malformée bloquait aussi toutes les suivantes. Elle est mise en
   quarantaine persistante et signalée. Son `sent_at` reste NULL : aucune livraison fictive.
3. Le P&L du dashboard était reconstruit sur seulement 200 fills et diminuait/disparaissait
   avec l'historique. Le calcul utilise le ledger complet ; seules les lignes affichées sont limitées.
4. Des runs abandonnés restaient `RUNNING`. Le prochain propriétaire du verrou exclusif les
   classe `INTERRUPTED`, sans toucher un run encore actif ni inférer une exécution.
5. Un execution ID connu avec prix/quantité/identité contradictoires était ignoré. Il bloque
   maintenant la réconciliation. Un replay strictement identique reste idempotent.
6. Des valeurs d'exécution non finies pouvaient entrer en SQLite. Le ledger refuse désormais
   prix non finis et quantités non positives/non entières, transactionnellement.
7. Un replay de fills reçu SELL avant BUY échouait malgré des sessions cohérentes. L'import
   générique suit maintenant l'ordre des séances et traite BUY avant SELL, comme le workflow d'enchère.
8. La réconciliation simulée ne vérifiait que les quantités : prix/date/stratégie corrompus
   pouvaient passer. Les positions sont maintenant comparées intégralement aux fills et aux intentions.

Les phases pré-open/sorties relisent aussi cette cohérence avant de déclarer une préparation réussie.
Aucune règle économique modifiée ; aucune réécriture du broker ou du moteur de recherche.

## Simulation intégrée et limites de sa preuve

Données quotidiennes existantes, candidat chargé depuis le fichier gelé, **19 séances**
du 3 au 27 mars 2026, incluant le changement d'heure. **22 réouvertures de SQLite**, avec :

- panne data, aucune stratégie exécutée avant succès du rafraîchissement, reprise dans la même fenêtre ;
- crash après commit des fills mais avant acquittement du job : replay sans doublon ;
- projection TEST corrompue : blocage, réparation à partir du fill simulé enregistré ;
- payload Telegram malformé et panne de livraison : quarantaine/reprise et commandes utilisables ;
- backup/restore, routes dashboard, redémarrage avec kill switch actif.

Résultat : 9 intentions, 5 positions clôturées simulées, 1 entrée sans fill, 11 fills simulés,
0 doublon de fill/job réussi, 0 ordre/exécution broker. À l'arrêt, une position TEST et
les intentions futures restent dans la base isolée ; `/kill` n'a pas inventé de liquidation.
35 messages ont été capturés par l'API Telegram **simulée**, pas envoyés à l'utilisateur.
Les résultats détaillés sont dans `results/production_readiness/`.

Un test intégré synthétique couvre aussi Thanksgiving : signal le 25 novembre, entrée
le 27 novembre (demi-séance), sortie à la 9e séance le 9 décembre ; aucun événement le 26.
Ce test utilise des fixtures, pas des données futures réelles. Les tests d'enchère conservent
l'avertissement MOC de 26 secondes et les contrôles de timezone/identité/callback.
Ceci est un audit opérationnel, pas une nouvelle validation de rentabilité ou d'exécution réelle.

Suite complète : **238 tests réussis**, dont les **229 tests antérieurs** et 9 nouveaux tests.
Les dépendances manquantes après redémarrage ont été réinstallées uniquement dans un runtime
de test temporaire ; aucune exigence de production ou règle de recherche modifiée.

## Blocages restants, par importance

### P0 — avant tout PAPER autonome

- **Pas de contrôleur Paper branché au scheduler cloud.** Ses pré-open/exits sont des diagnostics.
  Le cœur sait construire LMT/OPG et MOC mais aucun service cloud ne pilote le cycle réel.
  Ne pas tenter de régler cela en activant une variable : le refus PAPER est intentionnel.
- Le contrôle générique doit encore garantir la récupération des fills après plusieurs séances
  hors ligne, des ordres expirés/annulés/rejetés et des identités broker en reprise. Le filtre
  `reqExecutions` n'explicite pas une plage historique ; la persistance de preuves complètes
  des enchères existe surtout dans le harness isolé. Un ordre absent reste bloquant, pas
  automatiquement déclaré annulé. Il faut une mission technique dédiée avec preuves IBKR,
  sans assouplir les contrôles ni inventer des fills.
- IB Gateway Linux/ARM64, authentification/2FA, API locale, reconnexion et fonctionnement
  plusieurs jours n'ont pas été exécutés sur serveur. Un process relancé n'est pas une session authentifiée.

### P1 — avant de revendiquer plusieurs semaines sans intervention

- **Fenêtre d'une séance entièrement manquée** : une intention/sortie simulée dépassée arrête
  la progression ; pas de rattrapage silencieux. Après plus de trois échecs de job, intervention
  requise. C'est un arrêt de sécurité conservé, pas une reprise autonome garantie.
- Yahoo reste une source gratuite sans garantie opérationnelle dans ce système : indisponibilité,
  barres finales retardées, révisions/ajustements et trous provoquent un blocage. Pas de source
  secondaire autorisée ni de gestion autonome des corporate actions du portefeuille réel.
- Les sauvegardes sont locales à la VM. La restauration a été testée, mais une copie hors VM
  privée et son exercice de reprise restent à organiser ; ne pas restaurer un ancien ledger en
  présence d'ordres broker sans nouvelle réconciliation.
- Le P&L affiché depuis le ledger générique est **brut**, calculé sur les prix de fills.
  Les commissions capturées dans le harness d'enchère ne sont pas consolidées dans ce
  calcul général ; aucune performance nette Paper n'est certifiée par cet audit.
- Pas de contrôle externe de VM disponible : VM éteinte, disque totalement plein ou Telegram
  indisponible peuvent empêcher une alerte. Le compte Oracle bloqué et la capacité régionale
  empêchent actuellement les vérifications Linux/stockage/reboot/systemd.
- Le kill switch est une barrière persistante, pas une liquidation automatique. Authentifications
  IBKR, panne prolongée, split ou état incertain demandent un opérateur. Les routines d'ordres
  ne remplacent pas cette supervision.

### P2 — exploitation et qualité de service

- Heartbeat écrit par le scheduler ; une longue attente data peut déclencher une alerte de
  retard sans que le processus soit mort. Latences/durées réelles à mesurer sur Oracle.
- Livraison Telegram « au moins une fois » : un arrêt après envoi et avant acquittement peut
  répéter une notification. `/kill` est idempotent ; aucune garantie de réponse instantanée
  en cas de panne réseau. Une erreur d'authentification/chat bloqué nécessite une intervention.
- Le dashboard reconstruit maintenant le P&L complet ; surveiller temps de lecture et taille
  SQLite avec l'historique. Les notifications invalides conservent leur preuve pour inspection.

## Passage exact à Oracle DRY_RUN après résolution du support

1. Confirmer que le compte est débloqué ; vérifier région principale, capacité A1, quotas
   **effectifs** et étiquettes Always Free avant toute création. Pas de service payant ni
   d'upgrade pour contourner une absence de capacité. Obtenir l'autorisation de la VM.
2. Sur le Mac, sélectionner cette branche et exporter le paquet minimal. Aucun secret/cache
   intraday/base Paper n'est copié. Depuis la racine du dépôt :

   ```bash
   python -m bot.deploy.bundle /tmp/market-lab-readiness.tar.gz
   scp /tmp/market-lab-readiness.tar.gz ubuntu@ADRESSE_VM:/tmp/
   ```

3. Sur la VM Ubuntu 24.04 autorisée :

   ```bash
   sudo tar -xzf /tmp/market-lab-readiness.tar.gz -C /opt
   sudo bash /opt/market-lab/bot/deploy/install.sh
   ```

   L'installateur prépare les unités mais ne les démarre pas. Vérifier sur Linux
   `systemd-analyze verify /etc/systemd/system/market-lab-*.service`.
4. Avec `sudoedit`, renseigner les variables privées dans `/etc/market-lab/cloud.env`,
   permissions 0640, jamais dans Git. Conserver `TRADING_MODE=DRY_RUN`,
   `TRADING_ENABLED=false` et la base `/var/lib/market-lab/dry-run.sqlite` isolée.
   Aucun transfert automatique de secrets du Mac. Configurer SSH avec clé et limiter
   22 à son IP ; ne pas ouvrir 4002/8765/VNC publiquement.
5. Lancer les services DRY_RUN puis Telegram, après configuration privée :

   ```bash
   sudo bash /opt/market-lab/bot/deploy/manage.sh start
   sudo bash /opt/market-lab/bot/deploy/manage.sh telegram
   ```

   Gateway n'est pas nécessaire à cette étape. Le scheduler reste désactivé dans SQLite
   jusqu'à activation privée depuis le dashboard. Démarrer avant une clôture complète
   pour produire un premier plan avant le pré-open suivant.
6. Ouvrir le tunnel depuis le Mac : `ssh -N -L 8765:127.0.0.1:8765 ubuntu@ADRESSE_VM`.
   Vérifier dashboard, `/status`, `/positions`, `/kill`, notifications TEST, puis arrêt/reprise
   des services et reboot de VM. Tester backup/restore sur un **nouveau chemin**, selon
   `DEPLOY_ORACLE.md`. Ne jamais écraser la base Paper existante.
7. Observer plusieurs séances réelles DRY_RUN, une demi-séance si disponible, source data,
   timings, ressources, coupure réseau, notifications et sauvegarde hors VM. Conserver
   les preuves. PAPER reste interdit sans nouvelle autorisation et résolution des P0.

## Reproduction de l'audit local

Avec les dépendances de tests installées dans le dépôt complet :

```bash
python -m unittest bot.test_readiness bot.test_cloud bot.test_bot \
  bot.test_auction_checkpoints bot.test_execution_time bot.test_telegram -q
python -m bot.production_audit \
  --daily-csv data/cache/v2_2026_check/ohlcv.csv \
  --start 2026-03-03 --end 2026-03-27 \
  --output-dir /tmp/market-lab-readiness-new
```

Le runner exige une base nouvelle, utilise des API locales simulées et ne transmet rien.
Le panel n'est ni téléchargé ni versionné. Le rapport n'affiche aucun secret.
