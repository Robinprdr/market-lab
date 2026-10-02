# V2 swing candidate — 2026 check: PASS

Candidate `2366a81673c5` loaded from frozen file; horizon 9 sessions; cost 0.20% round trip.
Price source Yahoo adjusted OHLC; panel SHA256 `3256efd4e19d65cdc7701676b844b789fac93ecc2d4927b561eaf3bbcb2255ac`; last complete session 2026-10-01.
Frozen candidate SHA256 `bbc8f266b284778aa268edcc326ed172e291f1ab95482092c58aef99a7c40015`. Frozen rules and V2 code were not edited.
Universe: fixed Top100 US V1, 100 stocks plus SPY. Earlier rows are feature warmup only.
Signal at close t, entry at next session Open, exit at close t+9; trades crossing the data end are purged.
Trades 106; win 59.43%; gross 4.5673%; net/expectancy 4.3673%; median net 2.7814%; PF 2.303.
Standardized portfolio: 10,000 USD initial, 10% equity per entry, max 5 positions, ticker order, no deferred orders; accepted 63; return 30.9521%; maximum drawdown -6.4127%.
Five largest net-contribution tickers: SNDK, WDC, LRCX, MU, DELL (62.45% of aggregate signal net contribution). Without them: 74 trades; average net 2.3493%; PF 1.650; portfolio return 15.2564%.
Monthly factor average net is positive in 8/9 active entry months; monthly detail is in monthly.csv.

## Intraday data feasibility

Alpaca credentials were absent in this environment, so no actual historical 1-minute feed or depth could be measured. The read-only six-ticker IEX/SIP audit and pagination/timezone tests are prepared; see alpaca_audit.json and research/v2_2026/README.md. Verdict: ALPACA_FREE_LIMITED pending a real Basic-account test. Alpaca documents live Basic IEX and historical SIP older than 15 minutes, but this account entitlement and multi-year completeness remain unverified. Massive Stocks Starter advertises five years of minute aggregates at US$29/month as a paid fallback.

The 2024–2025 validation had already been viewed in earlier research. The 2026 check uses the later fixed candidate but is still a retrospective backtest with revised daily data, idealized next-open/exit-close execution, and constant costs.
The verdict follows the criteria fixed in research/v2_2026/protocol.json. No parameter was retuned.
