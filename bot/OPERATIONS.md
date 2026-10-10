# Bot Operations + Monitoring V1

This layer is **DRY_RUN only**. It does not construct an IBKR client, transmit orders, enable PAPER, or change the frozen swing strategy. Bot Core writes SQLite; the monitor reads that ledger. `TRADING_ENABLED=false` is required for the scheduler and web server. LIVE remains unsupported by Bot Core.

## Local schedule

The scheduler uses the XNYS calendar and timezone-aware instants derived from `America/New_York`, independent of the Mac's local timezone. On a normal 16:00 ET close:

| Job | ET | Effect in DRY_RUN |
|---|---:|---|
| Local reconciliation | 07:30 | Checks that the DRY_RUN ledger contains no broker orders; does not connect to IBKR. |
| Exit check | 14:30 | Records due simulated exits; sends no order. |
| Market data refresh | 16:30 | Loads completed daily bars and records row count/error. |
| Daily strategy run | 16:45 | Reuses frozen strategy, writes signals, decisions and DRY_RUN intents. |

On a 13:00 ET early close the exit check moves to 11:30, refresh to 13:30 and daily run to 13:45. There are no jobs on NYSE holidays or weekends. A job may run for at most two hours after its scheduled time. A Mac that restarts later skips that run; it never replays a stale entry or exit. Successful jobs are idempotent by `(kind, session)` and the underlying intent ID remains unique. Failed data jobs can retry inside the same two-hour window. The service performs a health heartbeat every 60 seconds and persists its latest state and execution time in SQLite. The dashboard marks an enabled scheduler with a heartbeat older than three minutes as `ERROR`.

`python -m bot.launchd` prints a per-user macOS LaunchAgent. `python -m bot.launchd --install` installs and starts it with `RunAtLoad` and `KeepAlive`, so it restarts after login or a crash. Install from a Python environment where `requirements-bot.txt` is installed. The agent always sets `TRADING_MODE=DRY_RUN` and `TRADING_ENABLED=false`; it cannot be repurposed for PAPER by changing the ambient shell environment. The scheduler is disabled in SQLite by default. Enable it from the local dashboard after inspecting the installation.

## Commands

From the repository root:

```sh
python -m pip install -r requirements-bot.txt
TRADING_MODE=DRY_RUN TRADING_ENABLED=false python -m bot.status
TRADING_MODE=DRY_RUN TRADING_ENABLED=false python -m bot.operations --once
TRADING_MODE=DRY_RUN TRADING_ENABLED=false python -m bot.operations
TRADING_MODE=DRY_RUN TRADING_ENABLED=false python -m bot.web --port 8765
# Optional automatic restart on macOS:
python -m bot.launchd --install
```

The dashboard is at **http://127.0.0.1:8765/**, bound to localhost. It has Dashboard, Portfolio, Signals, Orders, Trades, and Errors sections plus `/api/state`. The DRY_RUN scheduler switch changes only the local SQLite control flag; it cannot set `TRADING_ENABLED=true` or submit a Paper order. A CSRF token protects the local POST route. Access from an iPhone or another host is deliberately unavailable until authentication and network exposure are designed. There is no scheduler cloud installation.

`bot.status` and the dashboard show broker and reconciliation status separately. Cash, exposure and P&L are marked unavailable when the ledger has no actual fills; simulated intents are not counted as trades. The status includes the last and next scheduled jobs, recent signals and decisions, pending intents, positions and errors.

## Before PAPER automation

The Paper account last reported EUR as its base currency and no verified USD buying cash. Keep `TRADING_ENABLED=false`. First verify USD buying capacity and complete the isolated one-share Paper order test, including acknowledgement, fill/reject handling, MOC exit and post-fill reconciliation. Review OPG/MOC exchange timing and the observed lifecycle before designing a separate PAPER scheduler. This DRY_RUN LaunchAgent must remain DRY_RUN.
