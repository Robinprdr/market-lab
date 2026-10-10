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

This never submits an order. It imports executions once by execution ID, checks auction timestamps, actual position and orders, and reports OPG/MOC separately. Full PASS requires both identified auction fills, zero positions/orders, coherent SQLite and timestamps inside the unchanged expected windows. A verified MOC fill outside its time window reports `MOC=EXECUTION_CONFIRMED_TIMING_UNVERIFIED`, `MOC_execution=CONFIRMED`, the exact timing difference and reconciliation independently. It never expands a window or asserts a true exchange closing-auction price. A known rejected/cancelled or still unresolved exit is reported as FAIL with the remaining position/order information. Missing or contradictory identity/execution evidence is an explicit STOP. Non-PASS verification still exits nonzero, including timing warnings (exit 2). The final report is saved in `data/cache/bot_core/auction_2026-10-09_report.json` and SQLite.

For 9 October: 09:20 ET = Friday 23:20 Brisbane; 09:35 ET = Friday 23:35 Brisbane; 16:10 ET = Saturday 10 October 06:10 Brisbane. Use another valid exchange session if this date has already passed. The entry command never silently rolls to a new session. Early-close deadlines are derived from the exchange calendar.

## Persistence and recovery

The existing `data/cache/bot_core/market_lab.sqlite` retains standard order intents, orders, executions and positions. Additional tables:

- `auction_sessions`: session, exact account, ticker, test marker, phase state, last reconciliation time, report.
- `auction_order_proofs`: deterministic order reference, side/session, reserved broker order ID persisted **before network submission**, permId, acknowledged flag, broker status and exact terms.
- `auction_execution_proofs`: execution ID, original exchange timestamp, broker permId/contract metadata, commissions when available and observation timestamp.

States include ENTRY_SUBMITTING, ENTRY_ACCEPTED, ENTRY_FILLED, EXIT_SUBMITTING, EXIT_ACCEPTED, EXIT_FILLED, CLOSED, CLOSED_WITH_TIMING_WARNING, FAILED and UNCERTAIN. A timing warning closes the verified flat-account lifecycle without falsely validating simulator timestamp accuracy; it does not permit resubmission. Fresh broker evidence can recover an acknowledged order after a crash between transmit and the SQLite acknowledgement update. An absent uncertain order cannot be resubmitted. A local FILLED flag alone cannot arm a sell. Persisted previously observed execution evidence can support later verification, but a fill missed while offline is not reconstructed from a changed position balance.

Each command locks the SQLite run while active. Restarting Python/Codex/Mac does not erase the ledger. Repeated commands relaunch broker reads; no automatic new order is created for an existing session/side. Normal strategy code and its safeguards remain unchanged.

## Limits and stop procedure

No Paper or Live order has been sent during implementation. Unit tests use a fake broker; actual OPG, MOC and Gateway-off execution remain unvalidated.

Gateway is needed to connect and retrieve data at each checkpoint. There is no continuous Python/Codex requirement. Closing Gateway after acknowledged transmission must still be tested empirically in Paper: persistent local state cannot guarantee that the broker's simulator fills with Gateway closed. If an order disappears, is rejected or cannot be matched, the next checkpoint stops. Do not claim Mac-off persistence is already validated. See [the documented architecture analysis](AUCTION_DISCONNECTED_DESIGN.md).

AAPL's Nasdaq LOO deadline is before 09:28 ET; the test uses a stricter 09:25 cutoff. [IBKR describes Nasdaq MOC acceptance until 15:55 and NYSE until 15:50 ET](https://www.interactivebrokers.eu/campus/trading-lessons/ibkr-desktop-market-on-close-order/); this workflow retains close-minus-60-minutes for submission. The fixed test limit remains prior unadjusted completed close +0.5%, rounded down, capped by existing risk controls. No authoritative pre-submit IBKR ceiling is exposed by the current adapter; it is logged as unknown and old rejection ceilings are not reused. A rejection means STOP, not retuning.

Kill switch: unset `TRADING_ENABLED` or create `data/cache/bot_core/auction_YYYY-MM-DD.stop` to block further submissions. Neither action cancels an already transmitted order. No automatic liquidation or substitute SELL occurs on failure. Keep this Paper account exclusive: another client selling the share after MOC acceptance can leave a working unmatched sell. No stock reduce-only guarantee is assumed.

Broker open/completed/execution history is limited. Reconnect promptly, preferably within the same ET trading date. If a fill was never captured and IBKR no longer supplies its execution evidence, obtain an auditable broker report and resolve explicitly; do not invent a fill or bypass reconciliation. Preserve the SQLite database and audit files across restarts.

## Audited Paper cycle, 9 October 2026

AAPL BUY LMT/OPG one share: orderId 8, permId 191425056, execution `0000e0d5.6ac95906.01.01`, $332.42 at 09:30:19 ET, fees $1.000003. AAPL SELL MOC/DAY one share: orderId 10, permId 191425064, execution `0000e0d5.6aca00b3.01.01`, $336.46, fees $1.006934. No replacement order was used. The MOC was first PendingSubmit, later observed PreSubmitted and ultimately Filled. Terminal completedOrder omitted the useful orderId (returned 0); the matching permId, orderRef, account, contract, MOC/DAY terms and actual execution orderId 10 identify it unambiguously.

Two raw MOC timestamps were returned: `20261010 05:59:34 Australia/Brisbane` and `20261009 15:59:34 US/Eastern`. Both normalize to `2026-10-09T19:59:34+00:00`, New York session 2026-10-09. The adapter previously extracted the raw calendar date, incorrectly assigning the Brisbane representation to October 10. All execution dates now derive from the explicit timezone converted to America/New_York, independent of host settings. Missing, invalid or ambiguous zones are rejected. Raw timestamps and normalized UTC/ET values are retained, and conflicting replays stop. Confirmed commissions survive replays where the callback is absent.

The MOC timestamp is 26 seconds before the scheduled 16:00 ET close. There is no evidence establishing the simulator's internal reason, timestamp accuracy or an actual exchange auction match. [IBKR's Paper documentation](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/) describes simulated top-of-book fills and differences from production. [Execution reference](https://www.interactivebrokers.com/docs/tws-api/ref/execution) documents server time, execution IDs and shares; it does not explain this 26-second discrepancy. A simulator artifact is plausible, not proven. No specific 26-second exception or expanded tolerance was added. The original MOC window remains close through close+10 minutes, including early-close sessions.

Verdict: Paper MOC order execution is confirmed; exact auction timing/price fidelity remains unvalidated. Final IBKR and SQLite positions zero, no working orders, both actual fills recorded. `CLOSED_WITH_TIMING_WARNING` represents these facts without leaving a fictitious open position or falsely declaring full temporal PASS. This one isolated cycle validates the order plumbing and restart/reconciliation path, not 24/7 availability, Gateway-off persistence or Live execution. Full automation must still preserve allowlisting, position checks, deadlines, duplicate prevention and explicit timing diagnostics.

## Callback authority and completed-order quantity

On 9 October 2026, Paper order 8 / permId 191425056 returned a completed-order protobuf with **explicit** `totalQuantity="0"`, `filledQuantity="1"`, status Filled. This is a broker-supplied terminal snapshot, not a missing-field decoding default. The previously acknowledged order was for one share; `execDetails` independently reported one AAPL BUY at $332.42 at 09:30:19 ET. The API does not establish why that terminal totalQuantity became zero; do not infer cancellation, absence of fill, or original order size from it.

Open-order callbacks validate original terms and identity. Completed-order callbacks validate terminal status and identity; zero totalQuantity is allowed only in terminal completed snapshots, and positive quantities must still match the one-share test. Both quantity fields remain in diagnostics. All callbacks are checked, so a valid completed snapshot cannot hide invalid open-order terms. Filled status or filledQuantity alone never creates a transaction: identified executions, matching orderId/permId/account/contract and positive execution shares/price are required. Execution IDs make replay idempotent. Broker positions are authoritative for reconciliation, independently of completed-order quantity. Terminal openOrder callbacks remain diagnostic evidence but are not treated as working orders.
