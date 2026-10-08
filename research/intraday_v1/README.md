# Intraday Research V1

LONG continuity study on the unchanged Top100_US V1 snapshot, plus SPY as a benchmark. No trading endpoint, broker order, or existing strategy is used. `results/intraday_v1/protocol.json` was written before the search. Exploration is 2018–2023, validation 2024–2025, final holdout 2026 through the recorded last complete session. This is a present-day universe with survivorship bias, not a point-in-time Top100.

## Reproduction

From the repository root, using Python 3.11+:

```sh
python -m venv /tmp/market-lab-intraday-venv
/tmp/market-lab-intraday-venv/bin/python -m pip install -r research/intraday_v1/requirements.txt
/tmp/market-lab-intraday-venv/bin/python -m unittest research.intraday_v1.test_intraday -v
/tmp/market-lab-intraday-venv/bin/python -u -m research.intraday_v1.run --stage all --workers 4
```

Supply `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` only through the environment. They are never written, printed, or stored in manifests. Market data endpoint only, SIP, split adjusted, explicit UTC historical end. `BRK-B` maps to Alpaca's `BRK.B` while retaining the frozen universe identity. `data/cache/intraday_v1/` is ignored by Git. Each ticker/year minute Parquet has a pagination/quality manifest; completed partitions are reused and audited with SHA-256. Features are processed per ticker/year and then per month; ten years of the panel are never loaded together.

For individual stages use `--stage download`, `audit`, `features`, `exploration`, `validation`, or `final`. An existing candidate freeze is immutable. The all-stage command verifies it and skips search; it never silently retunes. An intentional independent fresh research experiment requires a new protocol/output/cache location, not deletion and selection on holdout results.

## Temporal and execution contract

Minute timestamps are UTC bar starts. Regular-session exchange calendar, DST and early closes define the complete five-minute grid. Incomplete buckets stay NaN. Feature eligibility depends only on completeness observed so far; future gaps do not remove earlier signals. A missing bar in the holding interval makes that outcome unavailable. Entire missing sessions are diagnostics, not fabricated prices.

VWAP uses cumulative minute VWAP × volume. Opening ranges freeze after 5/15/30/60 minutes. Relative volume compares prior 20 observed sessions at the same slot (minimum ten). Volume percentile ranks current volume within the trailing 20 previous observed sessions plus current. EMA restarts each session. Daily context is strictly from a prior session. Cross-sectional ranks exclude SPY and use only contemporaneously observed universe members. No forward fill across time or tickers.

Signal at five-minute close → next five-minute Open. Fixed holds require 15/30/60/90/120 minutes fully available before that day's close; EOD uses the calendar's actual last bar, including early closes. One position per ticker per candidate; no overlapping same-ticker trades, no overnight. LONG gross = Exit / Entry − 1. Base cost = 14bp round trip on entry notional (3.5 commission + 1 half-spread + 2.5 slippage per side); stress = 28bp. Signal-close dollar volume ≥ $100k and bar range ≤ 5% are fixed feasibility screens, not optimized. Split-adjusted nominal prices are not used for an arbitrary price cutoff.

## Search and limitations

Eight named continuity families; deterministic bounded search capped at 6,000 distinct variants. Pass 1 uses family anchors plus a single ancillary condition; pass 2 selects promising exploration features; pass 3 combines them; pass 4 uses the fixed threshold dictionary; pass 5 freezes at most ten under predeclared net/stress/frequency/stability/concentration gates. No validation or final data are read by search. Frozen files include protocol, code, and identity-override hashes. Validation exact rules → KEEP/DROP; final only KEEP rules → PASS/WEAK/FAIL. No surviving candidate means final performance remains unopened, and its output has headers only.

`data_overrides.json` records company-identity boundaries before performance analysis. SPCX history before 12 June 2026 belongs to a predecessor ETF, not SpaceX, and is excluded from signals **and daily context**. DELL/GEV/SNDK use the previously audited regular-way boundaries of Top100 V1. The snapshot is unchanged. Provider corporate-action mappings and split adjustment are reconstructed present-day histories; anomalies remain in availability/quality/adjustment diagnostics.

Portfolio is secondary: $10k cash, $1k fixed notional, at most five positions, no leverage, deterministic entry-time/ticker ordering, five-minute mark-to-market. Fractional shares and percentage commissions are research assumptions; bid/ask and fill latency are unavailable. Equal-notional signal drawdown is not an equity percentage. A held-out pass does not remove multiple-testing, survivorship, or historical-period reuse bias; forward paper confirmation would remain necessary.

## Completed experiment

6,000 variants / eight families / 121 distinct threshold predicates. One frozen OR15 breakout candidate (range position ≥ 0.9; 60-minute return ≥ 2%; EOD exit) passed exploration. It was **DROP** in 2024–2025: 256 trades, below the predeclared minimum 300, and negative net mean in 2024. Positive aggregate performance is dominated by 9 April 2025; outside that date the validation mean is negative. No rule or gate was changed. **FAIL** for this research; 2026 performance and portfolio were intentionally not evaluated because no candidate was kept. Header-only final outputs represent this gate, not zero-return trading.

The cache audit also flags RTX on 3 April 2020: a −70.26% adjusted overnight price discontinuity. Intraday returns never cross it, but surrounding daily context is not proven corporate-action clean. No invented adjustment was applied. Historical minute VWAP precision varies; per-ticker/year diagnostics retain the VWAP-equals-Close frequency and out-of-range count. Download wall time includes interruptions; feature time includes waiting for download, so elapsed stage times overlap.
