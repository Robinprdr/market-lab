# TOP100_US — snapshot V1

100 entreprises américaines distinctes, une seule classe chacune. Snapshot
collecté le **2 octobre 2026**, figé dans `top100_us_v1.csv` ; aucun classement
n'est téléchargé ou recalculé lors du benchmark.

Source : [CompaniesMarketCap, classement USA](https://companiesmarketcap.com/usa/largest-companies-in-the-usa-by-market-cap/).
Les capitalisations sont en USD, valeurs indicatives publiées lors de la
collecte, sans garantie de synchronisation intrajournalière entre les titres.
Empreinte SHA256 de la page collectée :
`1225f14abcd670a72bc0f2e7f581126875873c81a3b9ad0ffb9053f0b5e58c26`.

La sélection reprend les 100 sociétés du classement USA, sans ETF/fonds ni
ADR étrangers. Les REIT américains WELL/PLD sont des actions de sociétés,
pas des ETF. Alphabet conserve GOOG uniquement ; Berkshire conserve BRK-B.
Les noms et tickers sont uniques. La classification de domicile provient du
classement USA du fournisseur ; ce n'est pas un audit juridique des filiales.

SPCX reste dans le snapshot mais n'a pas de prix en 2018–2025 : la
[SEC confirme une première cotation le 12 juin 2026](https://www.sec.gov/Archives/edgar/data/1181412/000162828026042466/spaceexplorationtechnologi.htm).
Il n'est remplacé par aucun titre bénéficiant d'un historique plus favorable.
Les autres historiques courts et les bornes auditées de DELL/DHR/GEV/SNDK
sont documentés dans `research/v1_benchmark/data_overrides.json` et dans
`results/v1_final_benchmark/audit.json`.

**Survivorship bias accepté** : appliquer la composition actuelle au passé
favorise les survivants et les gagnants devenus grandes capitalisations.
Ce fichier n'est pas un univers historique point-in-time. Il ne doit pas être
présenté comme représentatif de ce qu'un investisseur aurait sélectionné en 2018.
