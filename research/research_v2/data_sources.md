# Audit des données — 2 octobre 2026

## Ce qui a réellement été obtenu

- Daily : cache V1 Yahoo, OHLC ajustés, 2014–2025 pour chauffe et recherche,
  snapshot Top100 inchangé. 99 sociétés ont des observations, SPCX aucune
  avant 2026. Les exclusions de préhistorique DELL/DHR/GEV/SNDK de V1 sont
  conservées. Couverture détaillée : `results/v1_final_benchmark/audit.json`.
- Intraday : Yahoo Chart, 5 actions du snapshot (AAPL/NVDA/AMZN/JPM/XOM)
  et SPY, 25/09–01/10/2026, 11 706 lignes retournées dont 11 700 minutes RTH.
  Six points à 16:00 sont hors de l'intervalle [open, close) et exclus.
  2 340 barres 5m complètes, soit 78 × 5 séances × 6 symboles. Zéro séance
  RTH incomplète parmi les séries obtenues. Empreintes dans l'audit intraday.
- Requête réelle AAPL 1m au 01/01/2018 : HTTP 422 ; message du serveur :
  « The requested range must be within the last 30 days. » Une ancienne date
  non cotée ne permet pas d'inférer la couverture : ici le refus indique
  explicitement une limite d'historique. Pas de reconstitution artificielle.
- Aucun nom de variable de clé Alpaca/Massive/Polygon/Databento configuré.
  Aucun endpoint authentifié ni abonnement n'a donc été prétendument validé.

## Sources possibles

| Source | Historique/documentation | Coût et limites | Conclusion |
|---|---|---|---|
| Yahoo/yfinance | Documentation générale intraday limitée à 60 jours ; serveur 1m testé : 30 jours | Gratuit, disponibilité/quotas non garantis, historique révisable | Échantillon technique uniquement |
| Alpaca SIP historique | Depuis 2016 ; FAQ : end vieux d'au moins 15 min permet le SIP historique sans abonnement | Basic annoncé gratuit, 200 requêtes/min, compte/clés requis ; Plus 99 USD/mois notamment pour SIP récent | Premier provider à vérifier avec des clés ; ne pas remplacer SIP par IEX silencieusement |
| Massive | Basic annoncé 2 ans et minute aggregates ; Starter 5 ans ; Developer 10 ans | Basic 0 USD/5 appels-min ; Starter 29 USD/mois ; Developer 79 USD/mois ; Advanced 199 USD/mois, quotes incluses | Alternative reproductible avec entitlements à tester, tarifs usage individuel |
| CSV 1m audité | Dépend du fournisseur de l'export | Provenance, fuseau, ajustements, calendrier et données manquantes à contrôler | Interface hors ligne implémentée |

Sources officielles consultées :
- https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html
- https://docs.alpaca.markets/us/docs/about-market-data-api
- https://docs.alpaca.markets/us/docs/market-data-faq
- https://docs.alpaca.markets/us/reference/stockbars
- https://massive.com/pricing
- https://massive.com/knowledge-base/article/how-much-historical-stock-data-does-massive-have

Les prix ci-dessus ne sont ni un achat ni une confirmation des droits de ce
compte. Une source gratuite pluriannuelle semble possible avec un compte
Alpaca ; elle n'est **pas accessible/testée dans cet environnement sans clés**.
Ne pas conclure abusivement qu'une API payante est obligatoirement nécessaire.

## Contrat du provider et volumes

`get_bars(ticker, start, end, timeframe=1)` retourne les débuts de minutes UTC,
OHLCV, et éventuellement VWAP minute. La fin est exclusive. Les feeds sont
explicites ; pas de données IEX mélangées aux volumes SIP. L'interface Alpaca
suit toute la pagination, utilise uniquement `data.alpaca.markets`, et cache
les réponses sans identifiants. Elle n'appelle aucun endpoint d'ordres.

L'agrégateur utilise XNYS (`exchange-calendars` 4.13.2), DST, jours fériés et
clôtures anticipées. Il ignore pre/post-market et impose des intervalles
complets. Une séance manquante/incomplète doit être résolue avant la recherche,
pas comblée avec le prix du lendemain. Un CSV externe doit préciser son fuseau.

Environ 9,8 millions de lignes 1m par an pour 100 titres, plus SPY. Commencer
par un petit lot ancien/récent, vérifier ajustements/volumes/horaires, puis
élargir. Aucun téléchargement historique complet n'est lancé ici. L'implémentation
locale conserve les features en cache ; le traitement complet de nombreuses
années demanderait un chargement par lots et une mesure de mémoire avant exécution.

Les barres ne donnent pas le spread réellement négociable. Coûts intraday
préfixés : demi-spread 2 bp + slippage 2 bp + commission 0,5 bp **par côté**,
soit 9 bp aller-retour, stress 18 bp. Hypothèse prudente de recherche, pas une
estimation observée ni une garantie pour chaque titre/heure. Le VWAP Yahoo
est un proxy du prix typique minute pondéré par volume ; Alpaca peut fournir
un VWAP minute issu des trades. Entrée au prochain Open idéalisée sans latence.
