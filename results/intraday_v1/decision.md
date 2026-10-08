# Intraday Research V1 — FAIL

Protocol fixed before search: exploration 2018–2023; validation 2024–2025; final 2026-01-01 to 2026-10-07. LONG only, regular session only, signal at five-minute close, next bar open, same-day fixed horizons 15/30/60/90/120 minutes or EOD. Fixed holds require their full length; signals too near close are ineligible for that horizon.

Data: SIP, split adjusted, symbol asof 2026-10-02; 81,810,868 cached regular minute bars, of which 81,777,735 belong to the retained company identities; 33,133 predecessor/when-issued bars excluded; 2,911,251,283 source cache bytes; download 33312.0s. Nonexistent listing periods are not fabricated. Current Top100 snapshot introduces survivorship bias; some present-day symbols have unusual history/renaming. See availability.csv and data_quality.csv.

Features use scheduled bars, leave holes empty, never compress time. All prior-day context is strictly before the session. OR is unavailable until its interval closes; VWAP uses only observed minute price/volume; RVol uses prior same-slot sessions. Cross-sectional ranks use only contemporaneously observed members. Missing or incomplete holding intervals make outcomes unavailable, not zero. No orders were sent and no trading endpoints were used.

Search: 6000 variants; 8 families; 121 distinct tested threshold predicates; one to four simple predicates. Maximum ten frozen candidates; predeclared frequency/net/stress/annual/concentration gates. Multiple testing makes exploration results selection-biased, not evidence of robustness. No dynamic exits were added.

Costs: 14bp round trip (3.5bp commission + 1bp half-spread + 2.5bp slippage per side), stress 28bp. LONG gross = exit/entry - 1; fixed costs are deducted on entry notional. Bar ranges are a liquidity proxy, not a measured bid/ask spread. No prices were substituted across holes.

Frozen candidates: 1. Validation verdicts are in validation_2024_2025.csv. Final evaluated candidates: 0. Final verdict: **FAIL**. If no candidate is kept, the final holdout performance is not opened and final files are intentionally empty. This is a completed rejection, not permission to tune new filters on 2024–2026.

Validation IV1_02791: best date 2025-04-09, 47 trades, net contribution 4.143441 in summed return units; excluding that date, 209 trades with mean net -0.2219%. This is a diagnostic, not a new rule or threshold.


Known adjustment exception: RTX on 2020-04-03 shows a -70.26% split-adjusted overnight discontinuity. No overnight PnL is measured, but nearby daily context requires a separate corporate-action audit. It was flagged, not repaired or used to retune this experiment. Historical quote/VWAP precision also varies by ticker/year; see availability.csv.

Performance timing: the minute download wall time includes interruptions and resumptions; its final resumed run took 815.6s. Feature elapsed time includes waiting for source partitions and overlaps download; it is not additive with download. Search computation took 140.0s.

Top raw exploration means (may fail minimum sample/stress/concentration gates):

```
2025-04-09
```

Quality: 215,559 diagnostics. Within retained company-identity periods: 1,470,975 missing source minutes and 0 invalid bars. Partial listing years and source exceptions are explicitly retained. Equity drawdown in portfolio_summary is five-minute mark-to-market; signal_drawdown is an equal-notional cumulative signal sum and is not a portfolio percentage. Portfolio uses $10k cash, $1k fixed notional, maximum five simultaneous positions, no leverage; fractional shares are a research assumption.

Limits: Current Top100 snapshot has survivorship bias. 2024–2026 calendar periods were seen in earlier families; no fully independent prospective proof. Bars do not identify bid/ask spread; costs are scenarios. Fixed notional signal study assumes fractional shares; standardized research portfolio, not execution-ready. Cached adjusted histories are provider snapshots, not a reconstructed historical universe. Price-only data do not measure opening latency or exact execution. Final 2026 is isolated from this search but earlier research already observed parts of these calendar years. A research PASS would require prospective/paper confirmation, not deployment.

No main merge; no strategy modifications; no brokerage trading. Stop after this mission.
