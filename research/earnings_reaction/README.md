# Audited earnings event calendar

This directory builds a causal quarterly earnings calendar for the project's 47-ticker universe from 2018 through 2025. It contains event timing only: no trading signals, returns, or PnL.

## Sources and inclusion logic

The standard pipeline starts from SEC EDGAR Forms 8-K/8-K-A whose submissions metadata identifies Item 2.02. It downloads the filed document, confirms conventional quarterly results, extracts fiscal fields when available, and records the SEC acceptance timestamp. The accession number and primary-document URL make each retained event auditable.

Item 2.02 does not always represent a normal quarterly release. Explicit accession-level exclusions cover guidance updates, preannouncements, preliminary results, Tesla production/delivery reports, amendments or duplicates, and other non-quarterly disclosures. The exclusion registry and generated exclusion CSV preserve the evidence and reason. Unresolved or ambiguous events cannot enter the final calendar.

## Temporal rules

SEC acceptance is the conservative public-availability timestamp and is converted from UTC to `America/New_York` with daylight-saving rules.

- **BMO:** accepted before 09:30 ET. The filing date is the complete reaction session; the following market session is the earliest causal entry after observing that full reaction.
- **AMC:** accepted at or after 16:00 ET. The next market session is the complete reaction session; the session after that is the earliest causal entry.
- **INTRADAY:** accepted from 09:30 through 15:59:59 ET. It is never treated as known at that day's open. The next market session is the complete reaction session and the session after that is the earliest causal entry.
- **UNKNOWN:** excluded until its timing can be resolved conservatively.

The 13 retained INTRADAY cases keep this SEC-based conservative rule. They may be revalidated against additional contemporaneous sources only if Earnings Reaction later shows enough promise to justify that work.

## SEC metadata exceptions

[`event_overrides_full.json`](event_overrides_full.json) contains the only two overrides. Both are exceptions to candidate discovery, not exceptions to the causal timing rules.

- **GE Q1 2020, 2020-04-29:** accession `0000040545-20-000019` is indexed without Item 2.02, but its primary filing explicitly contains Item 2.02 and says GE released first-quarter results. GE's official release confirms the quarter ended 2020-03-31. SEC acceptance at 06:27:17 ET establishes BMO availability; reaction session is 2020-04-29 and earliest causal entry is 2020-04-30.
- **Morgan Stanley Q2 2019, 2019-07-18:** accession `0001157523-19-001537` is miscoded in submissions metadata, but its primary filing explicitly contains Item 2.02 and the quarterly release. Morgan Stanley's official investor notice scheduled publication at approximately 07:30 ET. The exact SEC acceptance at 07:30:47 ET establishes BMO availability without inventing an hour; reaction session is 2019-07-18 and earliest causal entry is 2019-07-19.

## Reproduction and outputs

Run `build_calendar_full.py` from the repository root. The SEC user-agent can be overridden on the command line. Downloads are cached outside the repository.

Useful versioned outputs are:

- `results/earnings_reaction/calendar_full.csv`: retained event calendar;
- `results/earnings_reaction/event_overrides_full.csv`: flattened audit trail for the two metadata overrides;
- `results/earnings_reaction/excluded_item_2_02_full.csv`: all reviewed false positives;
- `results/earnings_reaction/manual_checks_full.csv`: old/recent cross-sector checks and all exceptional time classes;
- `results/earnings_reaction/quality_summary_full.json`: coverage, classification, and causal calendar checks.

Known limits include reliance on SEC acceptance as a conservative proxy for first public availability, incomplete fiscal-period extraction on some older documents, and possible earlier publication through another channel. The calendar intentionally chooses a later auditable timestamp when that uncertainty exists.
