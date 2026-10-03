# Market Lab Bot Core V1 — IBKR Paper only

For the local DRY_RUN scheduler and dashboard, see [OPERATIONS.md](OPERATIONS.md).

## Paper integration V1

Use IB Gateway **Simulated Trading** at `127.0.0.1:4002` with dedicated client ID `71`. Set `IBKR_ALLOWED_ACCOUNT_ID` privately to the exact DU paper account; the adapter refuses any other account for every request and order. Install `ibapi` from the official [IBKR TWS API distribution](https://interactivebrokers.github.io/) into the same Python environment as the research dependencies. No credential belongs in Git.

Run `python -m bot.ibkr_smoke_test` with `TRADING_ENABLED=false` first. It checks the socket, `nextValidId`, the allowlisted account, its account-specific cash/net liquidation/positions/open orders/executions, and reconnection. Run `python -m bot.reconcile` before enabling execution. The smoke test does not submit an order.

The pilot account reported **EUR** as its base currency on 2026-10-02. The adapter preserves its EUR cash and net liquidation for diagnostics but reports `available_cash_usd=0` for sizing; it never treats EUR as USD or assumes a margin/FX conversion. Thus entries and the isolated paper order trial are blocked until USD buying cash is unambiguously available or a separately reviewed FX-aware risk model exists. This is an intentional fail-closed limitation, not a strategy rule change.

`bot.paper_order_test` is an isolated one-share Paper `LMT+OPG` trial, using a verified prior-session unadjusted USD close supplied by the operator. It uses the same SQLite ledger, risk checks, account allowlist, reconciliation and durable submission claim. Without `--send` it only previews; with `--send` it submits once. It cannot submit while USD cash is unverified. Its test position is due for MOC on the entry date and must be handled by the normal `bot.run_exits` command before that day's cutoff. Run `bot.reconcile` afterward to record fills and confirm state. Do not use the frozen strategy ID for the test.

```sh
export IBKR_HOST=127.0.0.1 IBKR_PORT=4002 IBKR_CLIENT_ID=71
export IBKR_ALLOWED_ACCOUNT_ID=<exact DU paper account>
TRADING_MODE=PAPER TRADING_ENABLED=false python -m bot.ibkr_smoke_test
TRADING_MODE=PAPER TRADING_ENABLED=false python -m bot.reconcile
# Only after USD funds are verified and the prior unadjusted USD close is known:
TRADING_MODE=PAPER TRADING_ENABLED=true python -m bot.paper_order_test --ticker AAPL --reference-close <verified close> --send
TRADING_MODE=PAPER TRADING_ENABLED=true python -m bot.run_exits
TRADING_MODE=PAPER TRADING_ENABLED=false python -m bot.reconcile
```

All session checks use `America/New_York` and the NYSE calendar, including early closes. The intended automation is reconciliation at startup, `run_daily` after a completed U.S. close and before the next opening auction, and `run_exits` before the MOC cutoff. No scheduler is installed. Opening fills and MOC support remain unverified until an actual Paper order is accepted and completed; a rejected or uncertain order is never blindly resubmitted.

This bot loads frozen Research Engine V2 swing candidate `2366a81673c5` directly from `results/research_v2/frozen_candidates.json`, checking its companion hash and frozen research code. Signal: completed daily close `t`; intended entry at the next NYSE session's open; exit at the close of the **ninth trading session including entry day**. No indicator, threshold, signal filter or holding period is changed. The Top100 US V1 snapshot and Yahoo daily OHLCV provider remain separate from IBKR. The historical cost assumption is 0.20% round trip; real paper fills and fees will differ.

The executable parts are `config.py` (guarded settings), `strategy.py` (generic strategy interface and frozen candidate), `market_data.py`, `calendar.py`, `portfolio.py` (risk sizing), `broker_ibkr.py` (official TWS API socket adapter), `storage.py` (SQLite ledger), `runtime.py` (orchestration), and the `run_daily`, `run_exits`, `reconcile`, `status` commands.

## Execution model

- Run `bot.run_daily` after the completed U.S. close and before the next open. It downloads or reuses adjusted Yahoo daily bars, computes backward-looking V2 features, records all signals and decisions, reconciles the allowlisted paper account, and may submit entry orders without manual approval when `TRADING_ENABLED=true`.
- BUY uses a **limit-on-open** order (`LMT` + `OPG`) for the next session. The limit is at most 3% above the latest close by default and quantity is sized so the maximum fill notional respects the fixed risk limits. If the opening auction is above that cap, the order may not fill. A fill is not assumed to equal Yahoo's Open. The 3% is an execution safety cap, not a signal parameter; paper results cannot be equated directly with the backtest.
- Run `bot.run_exits` on every NYSE session **before close minus 60 minutes**. It reconciles positions and submits a SELL `MOC` on each position's ninth session. A missed or rejected MOC does not silently shift the holding horizon: it is logged and future entries stop when the position becomes overdue. Exchange-specific auction cutoffs and early closes need monitoring in the paper trial.
- Actual paper executions are written to SQLite. On later daily runs, each fill is compared with the **unadjusted** Yahoo Open (entry) or Close (exit); `fill_deviation_bps` is adverse-positive for either side. This is a diagnostic proxy, not an exchange auction print.
- Each order intent has a deterministic ID. State changes to `SUBMITTING` in SQLite **before** sending to IBKR. If connection fails between send and acknowledgement, the bot blocks on `RECONCILIATION_REQUIRED` rather than sending a second order. Broker positions are authoritative; an unexplained broker/DB difference also blocks orders.
- A nonblocking file lock prevents two daily/exit/reconciliation processes from placing orders concurrently against the same SQLite ledger. `status` remains read-only.

## Safety and configuration

`TRADING_MODE=PAPER` and `TRADING_ENABLED=false` are defaults. `LIVE` always raises. Paper broker access requires exactly one explicit `IBKR_ALLOWED_ACCOUNT_ID` beginning with `DU`, local host, and the paper TWS port 7497 or paper IB Gateway port 4002. With the kill switch off, local calculation and status work without connecting or configuring an account. The adapter requests account updates **only** for that ID and open orders for its dedicated nonzero client ID; it does not request all-account positions. Every order sets `order.account` to the allowlisted ID and repeats the check immediately before submission. A personal account is never selected implicitly.

| Environment variable | Default | Meaning |
|---|---:|---|
| `TRADING_MODE` | `PAPER` | `DRY_RUN` or `PAPER`; `LIVE` disabled |
| `TRADING_ENABLED` | `false` | Kill switch; only `true` permits orders |
| `IBKR_ALLOWED_ACCOUNT_ID` | unset | Exact paper DU account ID; required in PAPER |
| `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` | `127.0.0.1`, `7497`, `71` | Local paper socket, dedicated client ID |
| `BOT_DB_PATH` | `data/cache/bot_core/market_lab.sqlite` | Persistent ignored SQLite file |
| `BOT_INITIAL_EQUITY_USD` | `10000` | Fixed reference equity for sizing |
| `BOT_WEIGHT_PER_ENTRY` | `0.10` | 10% reference equity per entry |
| `BOT_MAX_POSITIONS` | `5` | Concurrent positions and pending buys |
| `BOT_MAX_EXPOSURE_PER_TICKER` | `0.10` | Per-ticker cap against reference equity |
| `BOT_MAX_TOTAL_EXPOSURE` | `0.50` | Aggregate cap against reference equity |
| `BOT_MAX_ORDER_NOTIONAL_USD` | `1000` | Hard pre-order cap at LOO limit price |
| `BOT_MAX_ORDERS_PER_DAY` | `5` | Daily order count cap; due exits reserve slots before new entries |
| `BOT_MAX_ENTRY_PRICE_DRIFT` | `0.03` | LOO cap relative to signal close |

Do not store credentials or the paper account ID in Git. Keep TWS/IB Gateway authenticated to the **paper** account and enable socket API on the matching paper port. To allow PAPER orders, disable TWS's API read-only setting for that paper session; keep `TRADING_ENABLED=false` until this has been checked. IBKR's official Python `ibapi` package must be installed from the official [TWS API distribution](https://ibkrcampus.com/campus/trading-lessons/accessing-the-tws-python-api-source-code/) into the runtime used for PAPER. It is imported only when a paper connection is attempted. Session authentication and any 2FA are managed by TWS/IB Gateway, never by this repository. If the gateway disconnects or a callback times out, the run fails closed. IBKR execution lookback can be limited by TWS trade-log settings; after prolonged downtime, reconciliation may require investigation.

The notional, exposure and price caps constrain **new buys**. An exit may exceed the original buy cap after a price gain; it reduces risk and is not blocked by that buy cap. The daily order-count cap still applies to exits, and new buys reserve room for already scheduled exits.

IBKR documents the [paper ports and API settings](https://ibkrcampus.com/campus/trading-lessons/installing-configuring-tws-for-the-api/), [`OPG` opening orders](https://interactivebrokers.github.io/tws-api/basic_orders.html), [order/account fields](https://ibkrcampus.com/docs/tws-api/ref/order), and [execution callbacks](https://interactivebrokers.github.io/tws-api/executions_commissions.html). The deprecated IBKR GitHub page is used only for its documented `LMT+OPG` mechanics; current IBKR Campus documentation was checked for TWS configuration and fields.

## Commands

From the repository root, using a Python environment with `pandas`, `numpy`, `exchange_calendars` and, for PAPER only, official `ibapi`:

```sh
TRADING_MODE=DRY_RUN python -m bot.run_daily --asof 2026-10-01
TRADING_MODE=DRY_RUN python -m bot.status

# After exporting the exact DU paper account ID privately and logging TWS into paper:
TRADING_MODE=PAPER TRADING_ENABLED=false python -m bot.reconcile
TRADING_MODE=PAPER TRADING_ENABLED=true python -m bot.run_daily
TRADING_MODE=PAPER TRADING_ENABLED=true python -m bot.run_exits
TRADING_MODE=PAPER python -m bot.status
```

Schedule `run_daily` after the daily Yahoo bar is complete, and `run_exits` before the NYSE close minus 60 minutes, accounting for U.S. holidays and half days. No scheduler, cloud deployment, Telegram, web app, short strategy, or live trading is included. DRY_RUN never connects or submits orders. The read-only Paper connection and reconciliation were verified on 2026-10-02; Paper order acceptance, fills, and auction behavior remain unverified while USD buying cash is unavailable. PAPER may require operator investigation after ambiguous submissions, rejected orders, partial fills, missing broker history, or external changes to the paper account.
