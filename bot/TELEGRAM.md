# Telegram V1 (privé)

Telegram relaie les événements persistés par Bot Core. Il n'exécute aucune stratégie ni aucun ordre. Les alertes d'ouverture et de clôture proviennent exclusivement d'exécutions enregistrées dans SQLite, pas de signaux ou de statuts d'ordres. Les messages comprennent les ouvertures, clôtures et P&L réalisé, le résumé quotidien, les erreurs critiques, la réconciliation bloquée et l'activation du kill switch. Le P&L réalisé affiché est **brut hors commissions** : le ledger ne stocke pas les commissions. Le P&L latent reste « indisponible » tant qu'aucun prix de marché actuel fiable, avec devise cohérente, n'est persisté ; aucun cours n'est inventé.

## Mise en place

1. Créer un bot via [@BotFather](https://t.me/BotFather) avec `/newbot`, puis conserver le token dans un gestionnaire de secrets.
2. Ouvrir une conversation **privée** avec le nouveau bot et lui envoyer `/start`.
3. Obtenir son identifiant numérique Telegram personnel : appeler `getUpdates` avec le token dans un environnement privé et relever `message.from.id` (égal à `message.chat.id` pour cette conversation privée). Ne pas partager ni enregistrer la réponse complète, qui contient des métadonnées personnelles. Une autre instance ne doit pas simultanément consommer les updates.
4. Définir `TELEGRAM_BOT_TOKEN` et `TELEGRAM_ALLOWED_USER_ID` dans l'environnement du processus, hors dépôt. Conserver `TRADING_MODE=DRY_RUN` et `TRADING_ENABLED=false` pour cette mission. La base SQLite doit être la même que Bot Core (`BOT_DB_PATH`, selon `bot/config.py`).
5. Depuis la racine du dépôt, lancer `python -m bot.telegram`. Le worker utilise le long polling et reprend après un redémarrage grâce à un offset SQLite. Le bot doit déjà avoir reçu `/start` pour pouvoir envoyer des messages privés.

Seuls `/status`, `/positions` et `/kill` sont acceptés. Les commandes d'un autre utilisateur, d'un autre chat ou d'un groupe sont ignorées. `/kill` désactive immédiatement les futurs ordres et le scheduler DRY_RUN, sans clôturer les positions. L'action est persistante et confirmée dans le chat. Elle est sérialisée avec la soumission d'ordres : une soumission déjà commencée peut s'achever avant que `/kill` soit confirmé ; aucune nouvelle soumission ne démarre ensuite. Il n'existe pas de `/resume`. Une remise à zéro locale exige `TRADING_MODE=DRY_RUN`, `TRADING_ENABLED=false`, puis `python -m bot.kill_switch --reset` ; avant tout retour au Paper, vérifier la réconciliation et les paramètres de sécurité.

Le transport masque les détails des exceptions réseau pour éviter de journaliser le token contenu dans l'URL Bot API. Ne pas exposer le dashboard local ni la base SQLite sur Internet. Protéger aussi les variables d'environnement, les sauvegardes de la base et les logs. L'outbox peut réessayer après un échec d'envoi ; une coupure entre envoi réussi et confirmation SQLite peut produire un doublon Telegram. Les tests V1 utilisent une API simulée : aucun message réel ni ordre IBKR n'est envoyé.

Référence : [Telegram Bot API](https://core.telegram.org/bots/api).
