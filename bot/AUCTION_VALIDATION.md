# Disconnected OPG / MOC Paper validation

Three short, independently restartable checkpoints replace the old continuous runner. No strategy changes; exact account DUR231204, AAPL, max one share. Entry is LMT/OPG, exit is MOC/DAY; both Transmit=True. There is no pre-submitted sell, bracket child, MARKET fallback or blind resubmission.

## Setup and commands

Run from the repository root with pandas, exchange_calendars and official IBKR ibapi installed. Gateway Paper must be logged in on localhost:4002 whenever a command runs. Client 82 must be reserved for this test. On this Codex Mac:

```sh
cd '/Users/robinperdreau/Documents/Codex/2026-09-08/github-plugin-github-openai-curated-remote-3/work/market-lab'
export PYTHONPATH='/private/tmp/market-lab-auction-test-deps:/Users/robinperdreau/Library/Python/3.9/lib/python/site-packages:data/cache/research_v2/deps:/Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python'
alias python='/Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
export TRADING_MODE=PAPER
export TRADING_ENABLED=true
export IBKR_ALLOWED_ACCOUNT_ID=DUR231204
export IBKR_PORT=4002
```

No secret is required by these commands. The `/tmp` dependency directory is session-specific; use an installed compatible environment if it has been removed. A LIVE/DRY_RUN setting or another account is refused. Trading defaults to disabled unless explicitly enabled as above.

1. **Before opening, around 09:20 ET**, between 09:00 inclusive and 09:25 exclusive:

```sh
python -m bot.auction_validation enter --session 2026-10-09
```

This reconciles a fresh account snapshot, requires zero positions/pending orders, verified settled USD and existing risk checks, sends one capped LMT/OPG and performs an explicit API reconnect to confirm broker-host acknowledgement, terms and nonzero permId. It does not wait for opening. Once the command succeeds, Python can exit. Do not confuse a local request with confirmed acceptance.

2. **After opening, around 09:35 ET**, before the conservative close-minus-60-minute deadline:

```sh
python -m bot.auction_validation arm-exit --session 2026-10-09
```

This retrieves broker executions, open/completed orders and actual position. A filled status without an identified one-share BUY execution is insufficient. Only an OPG fill in the expected opening time window, IBKR +1, matching SQLite +1 and reconciliation permit one MOC/DAY. It reconnects to confirm the accepted exit and returns; it does not wait for close. No fill means STOP with no SELL. An existing accepted/filled MOC is reported idempotently, not sent again.

3. **After closing, around 16:10 ET** on a normal session:

```sh
python -m bot.auction_validation verify-close --session 2026-10-09
```

This never submits an order. It imports executions once by execution ID, checks auction timestamps, actual position and orders, and reports OPG/MOC separately. PASS requires both identified auction fills, zero positions/orders and coherent SQLite. A known rejected/cancelled or still unresolved exit is reported as FAIL with the remaining position/order information. Missing or contradictory evidence is an explicit STOP. Non-PASS verification exits nonzero. The final report is saved in `data/cache/bot_core/auction_2026-10-09_report.json` and SQLite.

For 9 October: 09:20 ET = Friday 23:20 Brisbane; 09:35 ET = Friday 23:35 Brisbane; 16:10 ET = Saturday 10 October 06:10 Brisbane. Use another valid exchange session if this date has already passed. The entry command never silently rolls to a new session. Early-close deadlines are derived from the exchange calendar.

## Persistence and recovery

The existing `data/cache/bot_core/market_lab.sqlite` retains standard order intents, orders, executions and positions. Additional tables:

- `auction_sessions`: session, exact account, ticker, test marker, phase state, last reconciliation time, report.
- `auction_order_proofs`: deterministic order reference, side/session, reserved broker order ID persisted **before network submission**, permId, acknowledged flag, broker status and exact terms.
- `auction_execution_proofs`: execution ID, original exchange timestamp, broker permId/contract metadata, commissions when available and observation timestamp.

States include ENTRY_SUBMITTING, ENTRY_ACCEPTED, ENTRY_FILLED, EXIT_SUBMITTING, EXIT_ACCEPTED, EXIT_FILLED, CLOSED, FAILED and UNCERTAIN. Fresh broker evidence can recover an acknowledged order after a crash between transmit and the SQLite acknowledgement update. An absent uncertain order cannot be resubmitted. A local FILLED flag alone cannot arm a sell. Persisted previously observed execution evidence can support later verification, but a fill missed while offline is not reconstructed from a changed position balance.

Each command locks the SQLite run while active. Restarting Python/Codex/Mac does not erase the ledger. Repeated commands relaunch broker reads; no automatic new order is created for an existing session/side. Normal strategy code and its safeguards remain unchanged.

## Limits and stop procedure

No Paper or Live order has been sent during implementation. Unit tests use a fake broker; actual OPG, MOC and Gateway-off execution remain unvalidated.

Gateway is needed to connect and retrieve data at each checkpoint. There is no continuous Python/Codex requirement. Closing Gateway after acknowledged transmission must still be tested empirically in Paper: persistent local state cannot guarantee that the broker's simulator fills with Gateway closed. If an order disappears, is rejected or cannot be matched, the next checkpoint stops. Do not claim Mac-off persistence is already validated. See [the documented architecture analysis](AUCTION_DISCONNECTED_DESIGN.md).

AAPL's Nasdaq LOO deadline is before 09:28 ET; the test uses a stricter 09:25 cutoff. [IBKR describes Nasdaq MOC acceptance until 15:55 and NYSE until 15:50 ET](https://www.interactivebrokers.eu/campus/trading-lessons/ibkr-desktop-market-on-close-order/); this workflow retains close-minus-60-minutes for submission. The fixed test limit remains prior unadjusted completed close +0.5%, rounded down, capped by existing risk controls. No authoritative pre-submit IBKR ceiling is exposed by the current adapter; it is logged as unknown and old rejection ceilings are not reused. A rejection means STOP, not retuning.

Kill switch: unset `TRADING_ENABLED` or create `data/cache/bot_core/auction_YYYY-MM-DD.stop` to block further submissions. Neither action cancels an already transmitted order. No automatic liquidation or substitute SELL occurs on failure. Keep this Paper account exclusive: another client selling the share after MOC acceptance can leave a working unmatched sell. No stock reduce-only guarantee is assumed.

Broker open/completed/execution history is limited. Reconnect promptly, preferably within the same ET trading date. If a fill was never captured and IBKR no longer supplies its execution evidence, obtain an auditable broker report and resolve explicitly; do not invent a fill or bypass reconciliation. Preserve the SQLite database and audit files across restarts.
