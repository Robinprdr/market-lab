# Manual OPG / MOC Paper validation

Exact scope: DUR231204, AAPL, one share, PAPER_TEST_OPG. This command does not generate strategy signals or change Swing V2. It uses the existing SQLite ledger and risk preflight. It submits one LMT/OPG entry before opening, then one MOC/DAY exit immediately after the entry fill and reconciliation. It waits for closing execution and final flat reconciliation. No MARKET fallback, duplicate entry, automatic retry or blind resubmission.

Run on a day when the Mac can stay awake and IB Gateway Paper can remain connected throughout the session. Keep Gateway on localhost port 4002, exact allowlisted Paper account DUR231204. Client 82 must not be used by another process. The ledger is `data/cache/bot_core/market_lab.sqlite`; audit files are ignored JSONL files in that directory, including broker IDs, permIds, execution prices/times and commissions.

A preview is read-only against IBKR (no broker order) and records local diagnostics:

```sh
python -m bot.auction_validation --session 2026-10-09
```

Launch the real test on the specified NYSE session **between 09:00 and 09:30 America/New_York**, preferably 09:20. Keep the process running until after closing. Use your environment with pandas, exchange_calendars and the official IBKR ibapi installed:

```sh
caffeinate -i python -m bot.auction_validation --session 2026-10-09 --send
```

On this Codex Mac the exact bundled-runtime command is:

```sh
PYTHONPATH='/tmp/market-lab-intraday-deps:/Users/robinperdreau/Library/Python/3.9/lib/python/site-packages:data/cache/research_v2/deps:/Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python' caffeinate -i /Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m bot.auction_validation --session 2026-10-09 --send
```

Run from the repository root. Change only `--session` for a later test day; a non-session is refused. This command refuses late OPG submission, LIVE, wrong account, quantity >1, unexpected exposure/orders, insufficient settled USD and any previously attempted entry for that test session. The `/tmp` dependency directory is session-specific; use an installed environment if it no longer exists.

The test-only entry limit is prior completed unadjusted close +0.5%, rounded down to a cent, and is capped by existing risk controls. If a verified current broker ceiling is supplied to `safe_limit`, the limit is additionally capped 0.1% below that ceiling. The API currently supplies no authoritative pre-submit ceiling: this is logged as unknown, and a previous rejection ceiling is never reused as current. The 0.5% limit is not a guarantee of acceptance/fill. An IBKR rejection is a test failure, not a reason to retune or resubmit.

AAPL is listed on Nasdaq. [IBKR documents Nasdaq MOC acceptance until 15:55 ET and NYSE until 15:50 ET](https://www.interactivebrokers.eu/campus/trading-lessons/ibkr-desktop-market-on-close-order/). This harness keeps the project's stricter **close minus 60 minutes** submission cutoff, derived from the session calendar, including early closes. MOC is sent immediately after the OPG fill, well before the cutoff. Actual execution timestamps must fall at/after the scheduled auction (OPG within five minutes; MOC within ten minutes); ordinary-session fills do not qualify as auction validation.

Kill switch: create `data/cache/bot_core/auction_2026-10-09.stop`. It blocks a subsequent submission and stops monitoring with a diagnostic; it does not liquidate, cancel a working order or replace a MOC. Inspect IBKR directly if the process stops, the API disconnects or an order becomes uncertain. Never rerun blindly. Failures retain the ledger and capture completed-order cancellation reasons where available. A held position remains explicitly unresolved after failure; no automated substitute order is sent.

Status on 2026-10-08: real account preview passed; no OPG/MOC order submitted. Both real auction verdicts are **NOT_TESTED**, pending manual execution. The user opted for a manual launch; no scheduler or unattended order has been installed.
