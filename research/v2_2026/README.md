# Fixed Research Engine V2 check: 2026 and intraday data

This directory does not change the frozen V2 engine. `run.py` verifies the frozen file and loads candidate `2366a81673c5` with its exact rules, nine-session exit, and 0.20% round-trip cost. `protocol.json` fixed the evaluation end date, portfolio conventions, and PASS/WEAK/FAIL gates before the 2026 results were read. The Top100 US V1 snapshot is unchanged. Yahoo adjusted OHLCV from January 2025 through the last complete U.S. session provides warmup and 2026 prices; its raw responses and combined panel remain in ignored `data/cache/v2_2026_check/`. The results are retrospective and prices can be revised by the provider. No 2026 performance was used to fit the candidate.

Run from the repository root with the bundled Python and dependencies:

```sh
export PYTHONPATH="data/cache/research_v2/deps:/Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python"
PY=/Users/robinperdreau/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$PY" -m research.v2_2026.download_daily
"$PY" -m research.v2_2026.run
"$PY" -m research.v2_2026.audit_alpaca
"$PY" -m unittest discover -s research -p 'test*.py'
```

For the real Alpaca audit, set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` privately in the environment and rerun `audit_alpaca`. If the credentials are confirmed on Basic/free in the Alpaca account dashboard, append `--basic-account-confirmed`. Never write keys in this repository. The audit tests AAPL, MSFT, NVDA, AMZN, META and SPY on both IEX and SIP over June 2018 and September 2026, validates UTC and America/New_York time, regular sessions, OHLCV, minute gaps, and pagination through the existing provider. Alpaca documents Basic live IEX and historical SIP queries at least 15 minutes old; actual entitlement and completeness require account credentials. IEX covers one exchange and is not a substitute for full-market SIP minute data. See [Alpaca market data plans](https://docs.alpaca.markets/us/docs/about-market-data-api), [historical FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), and [feed descriptions](https://docs.alpaca.markets/us/docs/historical-stock-data-1).

If free Alpaca cannot provide complete multi-year SIP minutes, [Massive Stocks Starter](https://massive.com/pricing?product=stocks) currently advertises five years of minute aggregates at US$29/month; Developer advertises ten years at US$79/month. This is a source comparison, not a purchase or integration.
