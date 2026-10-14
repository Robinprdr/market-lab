# Oracle Cloud V1 : préparation, exclusivement DRY_RUN

Avant installation, lire [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) : corrections et blocages constatés lors du dernier audit.

Niveau A préparé et testé sur Mac. **Aucune VM créée, aucun ordre transmis.**
Niveau B : installation sur une VM autorisée, puis observation DRY_RUN.
Niveau C : Paper automatique, interdit avant autorisation séparée et validation sur Linux.
La stratégie Swing V2, son univers, son horizon de 9 séances et son sizing restent gelés.
L'avertissement historique `CLOSED_WITH_TIMING_WARNING` du MOC Paper est conservé.

## 1. Étapes personnelles : compte, région et gratuité

Créer son compte sur [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/).
Oracle peut demander téléphone et carte pour vérification : ne pas passer volontairement
en Pay As You Go, ne pas confondre crédit d'essai et ressources Always Free.
Choisir soigneusement sa **région principale**, puis vérifier dans la console les limites
et les ressources déjà consommées. La région du compte et sa capacité libre ne sont pas connues ici.
Ne créer aucune instance avant d'avoir confirmé l'étiquette Always Free et le coût affiché.

Vérification documentaire du 10 octobre 2026 : la [documentation OCI actuelle](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
indique pour A1 **1 500 OCPU-heures / 9 000 Go-heures par mois**, soit **2 OCPU / 12 Go**
en permanence au total. Ne pas reprendre aveuglément l'ancien quota 4 OCPU / 24 Go.
Référence proposée : `VM.Standard.A1.Flex`, ARM64, **2 OCPU, 12 Go, Ubuntu 24.04**, disque de
démarrage 50 Go. Le plafond gratuit de stockage boot + block est **200 Go au total**, avec
5 sauvegardes de volumes. Vérifier le quota et l'éligibilité de l'image dans sa console.
Ne pas ajouter de disque, IP, load balancer, sauvegarde ou service payant pour résoudre une panne.
La disponibilité A1 dans la région n'est pas garantie. Si « out of capacity », attendre.
Les E2.1.Micro x86 gratuits (1 Go de RAM, fraction d'OCPU) sont insuffisants pour cette pile :
pas de bascule automatique AMD. Aucune VM x86 payante n'est recommandée dans cette mission.

Coût visé : **0 $ seulement si tous les quotas et services restent effectivement Always Free**.
Activer un budget/alerte dans OCI ; une alerte ne constitue pas un plafond de facturation.
OCI peut récupérer les VM inactives : sur 7 jours, CPU et réseau sous 20 % et, pour A1,
mémoire sous 20 % selon les critères documentés. Ne pas fabriquer de charge pour contourner cette règle.
Une petite application peut être concernée. Sauvegarder hors VM vers un emplacement privé autorisé.
Les sauvegardes locales seules ne protègent pas contre la perte de l'instance/volume.

## 2. Réseau privé et clé SSH

Créer une clé SSH sur son ordinateur et ajouter **uniquement la clé publique** à OCI.
Garder la clé privée sur son ordinateur. Utiliser le compte Ubuntu initial, puis le compte
non privilégié `marketlab` pour les services. Aucun mot de passe SSH.
Dans Security List/NSG OCI : autoriser le port 22 seulement depuis son IP publique actuelle ;
aucun ingress 4002, 8765, 5900, 5901 ou port de diagnostic. Pas de dashboard public.
Après vérification d'une deuxième connexion SSH, configurer UFW (autoriser SSH depuis son IP,
refuser les autres entrées) et désactiver PasswordAuthentication dans sshd. Ces étapes réseau
restent manuelles pour éviter de couper l'accès par une IP erronée. L'installateur n'ouvre aucun port.
Le changement d'IP du partage de connexion nécessite de mettre à jour la règle SSH.

## 3. Installation automatisée après autorisation de la VM

Depuis la racine du dépôt local, créer un paquet contenant seulement le code et les entrées gelées :

```bash
python -m bot.deploy.bundle /tmp/market-lab-cloud.tar.gz
scp /tmp/market-lab-cloud.tar.gz ubuntu@ADRESSE_VM:/tmp/
```

Sur la VM autorisée :

```bash
sudo tar -xzf /tmp/market-lab-cloud.tar.gz -C /opt
sudo bash /opt/market-lab/bot/deploy/install.sh
```

Le script installe Python 3.12 dans un venv, les dépendances gelées, l'utilisateur de service,
les unités systemd et la rotation journald. Il **ne démarre aucun service**, ne provisionne
rien dans OCI et ne transfère aucun secret. Aucun cache intraday, aucune base Paper ou donnée
de marché volumineuse dans le paquet. Le fichier gelé et son digest sont inclus.
Ne pas extraire une mise à jour par-dessus un service actif : arrêter les services et conserver
une version de code de secours. Les données persistent séparément dans `/var/lib/market-lab`.

Fichier privé : `/etc/market-lab/cloud.env`, root:marketlab, mode 0640.
L'exemple conserve `DRY_RUN`, trading désactivé et une base distincte `dry-run.sqlite`.
Ouvrir ce fichier **sur le serveur** avec `sudoedit`, entrer uniquement les identifiants nécessaires
et le token Telegram actuel. Ne pas afficher son contenu, le coller dans un rapport, l'envoyer à Git,
ni copier automatiquement les secrets du Mac. Le compte autorisé et l'utilisateur Telegram doivent
être exactement ceux déjà autorisés dans la mission ; toute autre valeur est refusée par l'entrée cloud.
Alpaca n'est pas requis : laisser ses clés absentes. Aucune clé IBKR/mot de passe dans ce fichier.

## 4. Services et démarrage DRY_RUN

Les 18 dépendances résolues ont toutes une wheel compatible CPython 3.12/Linux ARM64 ;
leurs versions sont fixées dans `bot/deploy/constraints.txt`. Ce contrôle de distribution
ne remplace pas une installation/lancement réellement testé sur Ubuntu.

```bash
sudo bash /opt/market-lab/bot/deploy/manage.sh start
sudo bash /opt/market-lab/bot/deploy/manage.sh telegram
```

La deuxième commande est optionnelle, après configuration privée Telegram.
Les services démarrent avec le scheduler **désactivé dans SQLite** ; l'activer depuis le dashboard privé.
Systemd redémarre les processus en échec avec délai et limite de répétition. Pas de second scheduler :
verrou exclusif persistant tant que le processus est vivant. Les travaux réussis ne sont pas rejoués.
Trois échecs d'un travail imposent une inspection manuelle ; pas de resoumission aveugle.

Services permanents : scheduler (data/features/portfolio dans le même processus), dashboard Waitress
sur `127.0.0.1:8765`, Telegram long polling. Tâches indépendantes : santé toutes les 5 minutes,
sauvegarde quotidienne à 02:00 UTC. SQLite est une bibliothèque sur disque persistant, pas un serveur réseau.
Le scheduler exige les données rafraîchies avant la stratégie. DRY_RUN ne construit **aucun adaptateur IBKR**.
Gateway est un service optionnel : sa panne ne peut entraîner aucun ordre ni boucle de soumission.
Ne pas installer de service Paper automatique dans ce niveau B.

Depuis son ordinateur :

```bash
ssh -N -L 8765:127.0.0.1:8765 ubuntu@ADRESSE_VM
```

Ouvrir `http://127.0.0.1:8765`. Le dashboard reste privé, montre intents, simulation TEST,
jobs, erreurs, état et disque. Ses contrôles ont un jeton CSRF et ne peuvent activer Paper.
Telegram : `/status`, `/positions`, `/kill`, utilisateur **et chat privé** autorisés uniquement.
Pas de `/resume`. `/kill` persiste, interdit nouveaux intents et simulations ; ne ferme aucune position.
Les messages simulés portent `TEST / DRY_RUN — aucun ordre broker`.
Une coupure après envoi Telegram mais avant acquittement SQLite peut répéter une notification :
la livraison Telegram est au moins une fois, jamais une garantie « exactly once ».

## 5. Calendrier et causalité

Tous les calculs utilisent NYSE, America/New_York et des instants UTC conscients du fuseau.
Jours fériés/weekends exclus ; DST et clôtures anticipées proviennent d'exchange-calendars.

| Travail | Séance normale ET | Demi-séance ET |
|---|---|---|
| cohérence du ledger simulé | 07:30 | 07:30 |
| pré-ouverture, intentions de la clôture précédente | 09:15 à avant 09:25 | idem |
| contrôle des sorties planifiées | 14:30 | 11:30 |
| rafraîchissement et observation simulée des barres complètes | 16:30 | 13:30 |
| features + signal gelé + risque + intentions pour prochaine séance | 16:45 | 13:45 |

Les intentions après clôture ciblent la prochaine séance ; le pré-open explicite les relit.
En DRY_RUN il ne transmet rien. Le modèle LOO conserve le cap de prix original : un Open au-dessus
du cap est une simulation sans fill, pas une entrée inventée. Les fills simulés sont constatés
**après clôture**, dans `simulated_fills`/`simulated_positions`, jamais dans les tables broker.
Ce scénario ne prouve ni la latence réelle ni l'exécutabilité à l'enchère. Aucun nouveau backtest.
Si une séance simulée manque après une panne, état DATA_ERROR, pas de rattrapage silencieux.

Pour un futur Paper autorisé, il faudra relier le pré-open à une lecture IBKR récente et une
réconciliation réelle PASS, puis envoyer le LMT/OPG avant la limite interne 09:25.
Sortie MOC prévue 90 minutes avant close, cutoff interne conservateur close - 60 minutes.
L'acceptation réelle IBKR doit être constatée ; une préparation à 16:45 la veille n'est pas une preuve.
Ne pas activer simplement `TRADING_ENABLED=true` : les wrappers cloud refusent PAPER et LIVE.

## 6. IB Gateway Linux : installation et login restent à vérifier sur VM

La [page officielle IBKR](https://brokerage.ibkr.com/en/trading/ibgateway-latest.php) propose Linux ARM64.
Le lien stable officiel ARM a répondu HTTP 200 lors de cette préparation ; cela ne prouve pas le lancement
sur Ubuntu. Pas de machine Linux ici : installation, bibliothèques graphiques, socket et restart restent à tester.

Après autorisation, télécharger uniquement l'installateur officiel adapté :

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-arm.sh \
  -o /tmp/ibgateway-arm.sh
```

Le lancer interactivement et choisir `/opt/market-lab/ibgateway` pour que son lanceur soit
`/opt/market-lab/ibgateway/ibgateway`. Si le lanceur effectif diffère, adapter uniquement `start-gateway`.
Donner à marketlab l'accès à ce répertoire Gateway et à son propre répertoire de configuration,
pas l'écriture sur le reste du code. Installer l'API ibapi officielle seulement pour un futur test de lecture,
pas nécessaire au DRY_RUN. Ne pas utiliser IBC ou stocker un login pour contourner 2FA.

Le service display fournit Xvfb :99, TCP X11 désactivé. Pour voir l'écran, créer un mot de passe VNC
avec `x11vnc -storepasswd` en utilisateur marketlab, fichier privé dans son home. Démarrer temporairement
x11vnc avec `-display :99 -localhost -rfbauth /var/lib/market-lab/.vnc/passwd -rfbport 5901 -forever`.
Ne pas employer `-nopw`. Tunnel SSH vers 5901 uniquement. Se connecter à Gateway et choisir **Paper**,
activer API locale 4002, trusted IP 127.0.0.1 et API read-only pendant cette mission. Vérifier manuellement
le compte exact, puis fermer VNC. Ne jamais ouvrir 4002 sur Internet.

Gateway doit rester actif pour un futur bot Paper ; Python/Codex sur le Mac n'aura pas à rester ouvert.
Le [redémarrage Gateway officiel](https://www.interactivebrokers.com/docs/tws-api/doc/architecture/the-trader-workstation/the-ib-gateway)
ne garantit pas une session sans intervention : réauthentification hebdomadaire, 2FA, maintenance et
déconnexions peuvent nécessiter un login humain. Systemd peut relancer le processus, pas authentifier le compte.
Niveau B ne revendique aucune connexion/reconciliation broker : statut désactivé/inconnu explicitement.

Après installation et login Gateway, `IBKR_GATEWAY_MONITOR=true` permet au watchdog de tester
uniquement la joignabilité TCP locale 4002 et d'alerter en cas de perte. Une socket ouverte **ne prouve
pas une authentification ou une réconciliation broker** ; le dashboard distingue ce diagnostic.
Le smoke test de lecture local peut être utilisé séparément avec trading désactivé ; jamais activer
une soumission pour faire disparaître une alerte.

## 7. Santé, sauvegarde et restauration

Le watchdog détecte heartbeat absent/périmé, état d'erreur et disque libre inférieur à 1 Go.
Le dashboard affiche derniers jobs, mise à jour data, réconciliation **simulation uniquement**,
kill switch et redémarrage scheduler. Les erreurs cloud/Telegram sont neutralisées : aucune URL avec token
dans SQLite/journald. Telegram dépend d'Internet ; sans Telegram ou VM, aucune alerte externe garantie.
Un contrôle externe de disponibilité reste à organiser avant une prétention 24/7 ; aucune disponibilité SLA ici.

Backups : API SQLite `.backup()`, même en WAL, intégrité vérifiée, fichier 0600, publication atomique.
14 snapshots quotidiens conservés dans `/var/lib/market-lab/backups` ; logs journald plafonnés à 200 Mo/14 jours.
Tester une copie hors VM vers un emplacement privé autorisé. Jamais de simple copie à chaud du fichier SQLite seul.

Restauration, après arrêt des services, vers **un nouveau chemin** (jamais écraser la base Paper) :

```bash
sudo bash /opt/market-lab/bot/deploy/manage.sh stop
cd /opt/market-lab
sudo -u marketlab .venv/bin/python -m bot.backup restore \
  /var/lib/market-lab/backups/dry-run-YYYY-MM-DD.sqlite \
  /var/lib/market-lab/restored-dry-run.sqlite
```

Modifier uniquement BOT_DB_PATH dans le fichier privé avec sudoedit, puis redémarrer et vérifier dashboard/kill.
Une destination existante est refusée. La restauration peut répéter des notifications anciennes ; contrôler
l'outbox avant redémarrage Telegram. Ne pas restaurer une ancienne base en présence d'ordres broker réels.

## 8. Vérifications et arrêt

```bash
sudo bash /opt/market-lab/bot/deploy/manage.sh status
sudo journalctl -u market-lab-scheduler --since '30 minutes ago' --no-pager
sudo bash /opt/market-lab/bot/deploy/manage.sh stop
```

`stop` laisse le stockage intact. Pour empêcher le démarrage au reboot, désactiver les services/timers
avec systemctl disable ; `/kill` ne remplace pas l'arrêt Linux. Aucun service cloud ne gère les ordres.
Sur Ubuntu, vérifier `systemd-analyze verify /etc/systemd/system/market-lab-*.service`, redémarrage de VM,
dashboard tunnel, `/kill`, absence de double scheduler, backup/restore et mémoire disponible.
Ces vérifications Linux ne sont pas revendiquées comme réalisées sur Mac.

Avant Paper automatique : consentement explicite, validation Linux/Gateway/2FA, preuve du compte autorisé,
cash USD réglé vérifié sans conversion implicite, état broker récent, réconciliation PASS, API read-only
levée uniquement après accord, limites d'exposition inchangées, branche de contrôle autorisée et essais
des interruptions/états incertains. Conserver l'avertissement temporel du simulateur MOC ; ne pas élargir
sa fenêtre pour forcer un PASS. Aucun de ces éléments ne donne autorisation de nouveaux ordres aujourd'hui.

## 9. Reproduire les vérifications locales (dépôt complet)

Avec les dépendances installées dans son environnement Python, depuis la racine du dépôt :

```bash
python -m unittest bot.test_cloud bot.test_operations bot.test_telegram -q
python -m bot.cloud_smoke_test \
  --daily-csv data/cache/v2_2026_check/ohlcv.csv \
  --signal-date 2026-03-03 --output-dir /tmp/market-lab-cloud-scenario-new
```

Le scénario exige un nouveau dossier/base et les données quotidiennes déjà présentes ; il ne les
embarque pas dans le paquet. Il charge le candidat gelé, applique les risques existants et ne
cherche aucun paramètre. `--telegram` est optionnel pour délivrer les seuls événements TEST, si
les variables privées sont présentes. Sans cette option, le transport est capturé en mémoire.
Une base test distincte sert au redémarrage, aux doublons et à la restauration. Les comptes/rendements
broker existants ne sont pas modifiés. Voir `results/oracle_deployment/local_validation.json`
pour la preuve synthétique et les limites constatées.
