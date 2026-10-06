# Multi-currency cash guard

The adapter subscribes only to the allowlisted Paper account. Account aggregates (`NetLiquidation`, `AvailableFunds`, `TotalCashValue`) remain in the reported base currency. Actual balances (`CashBalance`, `TotalCashBalance`) are stored independently in `cash_by_currency`. Currency-specific funds and settlement balances have separate maps; `available_cash` is the verified USD amount used by existing risk checks. No implicit exchange rate is used.

Current Gateway versions may prefix currency ledger tags with `$LEDGER-`; ignoring these tags caused the previous USD balance to be invisible. The parser accepts both prefixed and legacy keys and excludes pseudo-currency `BASE`. It never substitutes `TotalCashValue` or `BuyingPower` for actual USD cash. [Official IBKR prefix documentation](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/per-currency-account-value-prefix).

Verified USD is bounded by actual cash and, when present, the USD settled balance and USD AvailableFunds. `SettledCashByDate` is evaluated against today's America/New_York date: only the latest balance on/before today is eligible, never a future settlement. Missing, malformed, nonfinite or unsupported values fail closed. At least one USD availability/settlement source is required in addition to the actual USD balance. Nonpositive global account AvailableFunds also blocks entries without any conversion. The entry risk check reserves at least 5 USD per new/pending buy for costs/buffer in addition to limit-price notional. This is a safety reserve, not a fee calculation or strategy parameter.

For USD stock exposure, the broker callback uses quantity × marketPrice in the contract's USD currency, rather than account-base marketValue. Non-USD stock exposure or an invalid market price blocks the snapshot. This prevents newly supported EUR-base accounts from understating USD exposure limits. Existing account allowlisting, Paper-only ports/mode, quantity/position/exposure caps and submission idempotency remain active.

Read-only verification on 6 October 2026 (Australia/Brisbane): base EUR, actual USD ledger cash visible, no USD AvailableFunds tag, and USD `SettledCashByDate` showing zero until a positive balance dated 7 October 2026. Therefore `USD_CASH_CONFIRMED` describes the existence of actual USD cash, **not permission to trade**: verified usable USD was zero and the order preflight remained blocked. Broker/SQLite reconciliation passed with no open positions or orders. No order was sent. Re-query after settlement; do not assume that the future balance has become available merely because a date has passed.

Reproduction, with the exact Paper account set privately in `IBKR_ALLOWED_ACCOUNT_ID`, official `ibapi`, Python 3.10+ and project dependencies:

```sh
TRADING_MODE=PAPER TRADING_ENABLED=false IBKR_HOST=127.0.0.1 IBKR_PORT=4002 python -m bot.ibkr_smoke_test
TRADING_MODE=PAPER TRADING_ENABLED=false IBKR_HOST=127.0.0.1 IBKR_PORT=4002 python -m bot.reconcile
python -m unittest bot.test_bot bot.test_account_cash
```

The existing isolated order command still uses LMT+OPG; this cash-only correction does not implement or execute the separate simple intraday entry/exit trial, nor validate OPG/MOC.
