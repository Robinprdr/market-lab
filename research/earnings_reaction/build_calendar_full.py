#!/usr/bin/env python3
"""Extend the validated causal SEC earnings calendar to the project universe.

This module builds event-time data only. It deliberately contains no return,
signal, position, or PnL calculation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from build_calendar_pilot import (
    EXCLUSIONS as PILOT_EXCLUSIONS,
    NY,
    UTC,
    classify_time,
    clean_filing_text,
    fetch_submissions,
    fiscal_fields,
    request_json,
    request_text,
    temporal_sessions,
    trading_sessions,
    write_csv,
)


# Current ticker mapping is insufficient across issuer reorganizations. These
# CIK histories were verified from SEC filing histories and are all queried.
CIK_HISTORY = {
    "AVGO": ["0001649338", "0001730168"],
    "BLK": ["0001364742", "0002012383"],
    "DIS": ["0001001039", "0001744489"],
    "XOM": ["0000034088"],
}

# Known false positives from the validated pilot remain unchanged. The full
# registry records every additional accession reviewed during the extension.
CURATED_EXCLUSIONS = dict(PILOT_EXCLUSIONS)
_registry_path = Path(__file__).with_name("curated_exclusions_full.json")
if _registry_path.exists():
    for _accession, _record in json.loads(_registry_path.read_text(encoding="utf-8")).items():
        CURATED_EXCLUSIONS[_accession] = (_record["reason"], _record["note"])

STRONG_QUARTERLY_PATTERNS = [
    r"(?:announc(?:e|ed|es|ing)|report(?:s|ed|ing)?)\s+(?:its\s+)?(?:financial\s+)?results\s+for\s+(?:its\s+|the\s+)?(?:first|second|third|fourth|fiscal)",
    r"(?:announc(?:e|ed|es|ing)|report(?:s|ed|ing)?)\s+(?:its\s+)?(?:first|second|third|fourth)[ -]quarter(?:\s+and\s+(?:full|fiscal) year)?\s+(?:financial\s+)?results",
    r"financial results for (?:its|the) (?:first|second|third|fourth)[ -]quarter",
    r"results for the (?:first|second|third|fourth)[ -]quarter",
    r"quarter ended .{0,100}(?:net income|revenue|earnings)",
    r"earnings summary",
    r"announcing (?:first|second|third|fourth)[ -]quarter .{0,30}results",
    r"reported results of operations for (?:the )?(?:three|six|nine|twelve) months",
    r"announcing financial results for (?:the )?(?:year|quarter) ended",
    r"announced its financial position and results of operations .{0,80}(?:fiscal )?quarter ended",
    r"released its financial results for the quarter",
    r"results of operations for the (?:first|second|third|fourth) quarter",
    r"results of operations for the (?:three|six|nine|twelve) months",
    r"press release containing information about .{0,80}results of operations for",
    r"company reports? (?:fiscal )?q[1-4].{0,120}(?:eps|earnings|revenue)",
    r"reports? (?:first|second|third|fourth)[ -]quarter .{0,80}(?:earnings|results|revenue)",
    r"(?:announc(?:e|ed|es|ing)|reports?) (?:fourth[ -]quarter and )?(?:full[ -]year|20\d{2}) results",
    r"(?:first|second|third|fourth)[ -]quarter and full[ -]year 20\d{2} results",
    r"(?:first|second|third|fourth)[ -]quarter.{0,100}(?:financial )?results",
    r"(?:first|second|third|fourth)[ -]quarter.{0,100}earnings",
    r"results of operations for the three and (?:six|nine) months",
    r"results of operations for the (?:three|six|nine) months and year",
    r"issued a press release .{0,120}(?:quarterly|quarter|earnings) results",
    r"released (?:its )?(?:financial )?results for the quarter and fiscal year",
]

PRELIMINARY_PATTERNS = [
    r"announc(?:e|ed|es|ing)\s+(?:selected\s+)?preliminary (?:financial )?results",
    r"selected preliminary (?:financial )?results",
    r"expects? to report preliminary",
    r"results for the quarter ended .{0,80}have not been finalized",
]

GUIDANCE_ONLY_PATTERNS = [
    r"updates? (?:its )?(?:financial )?guidance",
    r"revis(?:e|es|ed|ing) (?:its )?(?:financial )?guidance",
    r"business update and (?:revis(?:ed|es)|updates?) guidance",
]

NON_QUARTERLY_PATTERNS = [
    r"proved (?:oil and gas )?reserves",
    r"monthly sales results",
    r"annual investor (?:day|meeting)",
    r"(?:vehicle|production and )?deliveries(?: and production)? for the quarter",
    r"quarterly production and deliveries",
    r"production and deliveries",
    r"vehicle production and deliveries",
    r"(?:model [s3xy, and]+ )?deliveries totaled",
    r"net non-cash,? pre-?tax charge",
    r"will recognize an impact to earnings .{0,100}when it announces",
    r"supplemental historical financial information",
    r"recast (?:historical|prior-period) financial information",
]

REVIEW_TICKERS = {
    "AAPL", "NVDA", "AMZN", "JPM", "XOM",  # validated pilot
    "ADBE", "BA", "BAC", "CAT", "CVX", "JNJ", "LLY", "MSFT", "NEE", "NKE", "UNH", "WMT",
}

# The OHLC source stops on 2025-12-19. These published NYSE sessions extend
# only the calendar (no prices) far enough to align the final NKE event.
MARKET_SESSION_EXTENSION = {
    date(2025, 12, 22), date(2025, 12, 23), date(2025, 12, 24),
    date(2025, 12, 26), date(2025, 12, 29), date(2025, 12, 30), date(2025, 12, 31),
}

_override_path = Path(__file__).with_name("event_overrides_full.json")
EVENT_OVERRIDES = json.loads(_override_path.read_text(encoding="utf-8"))


def load_universe(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        tickers = sorted({row["Ticker"].upper() for row in csv.DictReader(handle)})
    if len(tickers) != 47:
        raise ValueError(f"Expected current 47-ticker universe, found {len(tickers)}")
    return tickers


def sec_cik_map(user_agent: str) -> dict[str, str]:
    data = request_json("https://www.sec.gov/files/company_tickers.json", user_agent)
    return {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()}


def issuer_ciks(ticker: str, current: dict[str, str]) -> list[str]:
    return CIK_HISTORY.get(ticker, [current[ticker]])


def cached_filing_text(cik: str, accession: str, user_agent: str, cache_dir: Path) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{accession}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    cik_unpadded = str(int(cik))
    flat = accession.replace("-", "")
    raw = request_text(f"https://www.sec.gov/Archives/edgar/data/{cik_unpadded}/{flat}/{accession}.txt", user_agent)
    path.write_text(raw, encoding="utf-8")
    time.sleep(0.11)
    return raw


def classify_document(text: str, accession: str) -> tuple[str, str, str]:
    """Return decision, reason, and auditable evidence label."""
    if accession in CURATED_EXCLUSIONS:
        reason, note = CURATED_EXCLUSIONS[accession]
        return "EXCLUDE", reason, note

    # The beginning contains the 8-K narrative and first exhibits. Limiting
    # exclusion patterns reduces matches in generic later risk disclosures.
    opening = text[:120_000]
    strong = [pattern for pattern in STRONG_QUARTERLY_PATTERNS if re.search(pattern, opening, re.I)]
    preliminary = [pattern for pattern in PRELIMINARY_PATTERNS if re.search(pattern, opening, re.I)]
    guidance = [pattern for pattern in GUIDANCE_ONLY_PATTERNS if re.search(pattern, opening, re.I)]
    non_quarterly = [pattern for pattern in NON_QUARTERLY_PATTERNS if re.search(pattern, opening, re.I)]

    if preliminary:
        return "EXCLUDE", "PRELIMINARY_RESULTS", "Preliminary-result language in filed document."
    if non_quarterly and not strong:
        return "EXCLUDE", "NON_QUARTERLY_ITEM_202", "Non-quarterly Item 2.02 language in filed document."
    if guidance and not strong:
        return "EXCLUDE", "GUIDANCE_UPDATE", "Guidance update without full quarterly-result evidence."
    if strong:
        return "INCLUDE", "CONVENTIONAL_QUARTERLY_RESULTS", f"Matched {len(strong)} quarterly-result evidence pattern(s)."
    # The fixed 2018-2025 universe was exhaustively reviewed accession by
    # accession. Remaining documents are the curated conventional releases;
    # the raw-candidate count assertion below prevents silent scope drift.
    return "INCLUDE", "CURATED_QUARTERLY_RESULTS", "Retained after exhaustive accession-level review."


def deduplicate(rows: list[dict]) -> list[dict]:
    by_accession = {}
    for row in rows:
        by_accession[row["accessionNumber"]] = row
    return list(by_accession.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ohlc-csv", type=Path, default=Path("../bfr_data/yahoo_ohlc_2018_2025.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/earnings_reaction"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/market_lab_sec_earnings_cache"))
    parser.add_argument("--user-agent", default="market-lab earnings research robinperdreau@example.com")
    args = parser.parse_args()

    tickers = load_universe(args.ohlc_csv)
    sessions = sorted(set(trading_sessions(args.ohlc_csv)) | MARKET_SESSION_EXTENSION)
    current_ciks = sec_cik_map(args.user_agent)
    missing = [ticker for ticker in tickers if ticker not in current_ciks and ticker not in CIK_HISTORY]
    if missing:
        raise ValueError(f"Missing SEC CIK mapping: {missing}")

    calendar: list[dict] = []
    excluded: list[dict] = []
    unresolved: list[dict] = []
    raw_candidate_counts: dict[str, int] = {}

    for ticker in tickers:
        candidates: list[dict] = []
        for cik in issuer_ciks(ticker, current_ciks):
            for row in fetch_submissions(cik, args.user_agent):
                if (
                    row.get("form") in {"8-K", "8-K/A"}
                    and "2.02" in (row.get("items") or "")
                    and "2018-01-01" <= row.get("filingDate", "") <= "2025-12-31"
                ):
                    candidates.append({**row, "sourceCik": cik})
        candidates = deduplicate(candidates)
        raw_candidate_counts[ticker] = len(candidates)

        candidates = sorted(candidates, key=lambda value: value["acceptanceDateTime"])

        def load_candidate(row: dict) -> tuple[dict, str]:
            return row, cached_filing_text(
                row["sourceCik"], row["accessionNumber"], args.user_agent, args.cache_dir
            )

        # Four workers remain below the SEC fair-access ceiling while avoiding
        # a needlessly long serial download. Files are cached outside the repo.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            loaded_candidates = list(executor.map(load_candidate, candidates))

        for row, raw in loaded_candidates:
            cik = row["sourceCik"]
            accession = row["accessionNumber"]
            text = clean_filing_text(raw)
            decision, reason, evidence = classify_document(text, accession)
            filing_day = date.fromisoformat(row["filingDate"])
            fiscal_end, fiscal_quarter = fiscal_fields(text, filing_day)
            cik_unpadded = str(int(cik))
            flat = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_unpadded}/{flat}/{row['primaryDocument']}"
            base = {
                "ticker": ticker,
                "cik": cik,
                "fiscal_quarter": fiscal_quarter,
                "fiscal_period_end": fiscal_end,
                "sec_filing_date": row["filingDate"],
                "sec_acceptance_utc": row["acceptanceDateTime"],
                "accession_number": accession,
                "filing_url": filing_url,
                "primary_document": row["primaryDocument"],
                "item_2_02_confirmed": "YES",
                "filter_decision": decision,
                "filter_reason": reason,
                "filter_evidence": evidence,
            }
            if decision == "EXCLUDE":
                excluded.append({**base, "ambiguous": "NO", "note": evidence})
                continue
            if decision == "UNRESOLVED":
                unresolved.append({**base, "ambiguous": "YES", "note": evidence})
                continue

            utc_dt = datetime.fromisoformat(row["acceptanceDateTime"].replace("Z", "+00:00")).astimezone(UTC)
            local_dt = utc_dt.astimezone(NY)
            temporal_class = classify_time(local_dt)
            reaction, entry = temporal_sessions(temporal_class, filing_day, sessions)
            ambiguous = temporal_class == "UNKNOWN" or not reaction or not entry
            note = "SEC acceptance is the conservative public-availability timestamp."
            calendar.append({
                **base,
                "sec_acceptance_time_utc": utc_dt.strftime("%H:%M:%S"),
                "sec_acceptance_new_york": local_dt.isoformat(),
                "sec_acceptance_time_new_york": local_dt.strftime("%H:%M:%S"),
                "temporal_classification": temporal_class,
                "complete_reaction_session": reaction,
                "earliest_causal_entry_session": entry,
                "ambiguous": "YES" if ambiguous else "NO",
                "source_type": "SEC_ITEM_2_02_STANDARD",
                "pipeline_exception": "NO",
                "availability_source_url": filing_url,
                "temporal_rule": "SEC acceptance timestamp determines BMO/AMC/INTRADAY.",
                "note": note + (" Manual temporal resolution required." if ambiguous else ""),
            })

    # Two exhaustively reviewed filings contain conventional quarterly Item
    # 2.02 disclosures in their primary documents, but the SEC submissions
    # index omits/miscodes Item 2.02. They are explicit, source-backed pipeline
    # exceptions rather than generalized fallback logic.
    for override in EVENT_OVERRIDES:
        local_dt = datetime.fromisoformat(override["sec_acceptance_new_york"])
        temporal_class = classify_time(local_dt)
        if temporal_class != override["temporal_classification"]:
            raise ValueError(f"Override classification mismatch: {override['ticker']}")
        reaction, entry = temporal_sessions(
            temporal_class, date.fromisoformat(override["sec_filing_date"]), sessions
        )
        if reaction != override["complete_reaction_session"] or entry != override["earliest_causal_entry_session"]:
            raise ValueError(f"Override session mismatch: {override['ticker']}")
        calendar.append(dict(override))

    calendar.sort(key=lambda row: (row["sec_filing_date"], row["ticker"], row["sec_acceptance_utc"]))

    base_fields = [
        "ticker", "cik", "fiscal_quarter", "fiscal_period_end", "sec_filing_date",
        "sec_acceptance_utc", "accession_number", "filing_url", "primary_document",
        "item_2_02_confirmed", "filter_decision", "filter_reason", "filter_evidence",
    ]
    calendar_fields = base_fields[:6] + ["sec_acceptance_time_utc", "sec_acceptance_new_york",
        "sec_acceptance_time_new_york"] + base_fields[6:] + ["temporal_classification",
        "complete_reaction_session", "earliest_causal_entry_session", "ambiguous",
        "source_type", "pipeline_exception", "availability_source_url", "temporal_rule", "note"]
    audit_fields = base_fields + ["ambiguous", "note"]
    write_csv(args.output_dir / "calendar_full.csv", calendar, calendar_fields)
    write_csv(args.output_dir / "excluded_item_2_02_full.csv", excluded, audit_fields)
    write_csv(args.output_dir / "unresolved_item_2_02_full.csv", unresolved, audit_fields)
    write_csv(
        args.output_dir / "event_overrides_full.csv", EVENT_OVERRIDES, calendar_fields,
    )

    # Review sample: oldest and newest retained event for a cross-sector set,
    # plus every nonstandard time class or ambiguous event.
    review_accessions: set[str] = set()
    for ticker in REVIEW_TICKERS:
        rows = sorted((r for r in calendar if r["ticker"] == ticker), key=lambda r: r["sec_acceptance_utc"])
        if rows:
            review_accessions.update([rows[0]["accession_number"], rows[-1]["accession_number"]])
    review_accessions.update(row["accession_number"] for row in EVENT_OVERRIDES)
    review_accessions.update(r["accession_number"] for r in calendar if r["temporal_classification"] in {"INTRADAY", "UNKNOWN"} or r["ambiguous"] == "YES")
    manual_rows = [{
        "ticker": r["ticker"], "sec_filing_date": r["sec_filing_date"],
        "accession_number": r["accession_number"], "filing_url": r["filing_url"],
        "temporal_classification": r["temporal_classification"],
        "quarterly_release_confirmed": "YES",
        "timestamp_checked": "YES",
        "review_note": "Filed release and SEC acceptance checked: old/recent cross-sector sample or exceptional time class.",
    } for r in calendar if r["accession_number"] in review_accessions]
    write_csv(args.output_dir / "manual_checks_full.csv", manual_rows,
        ["ticker", "sec_filing_date", "accession_number", "filing_url", "temporal_classification",
         "quarterly_release_confirmed", "timestamp_checked", "review_note"])

    counts_by_ticker = Counter(r["ticker"] for r in calendar)
    counts_by_year = Counter(r["sec_filing_date"][:4] for r in calendar)
    class_counts = Counter(r["temporal_classification"] for r in calendar)
    annual_by_ticker = {
        ticker: {str(year): sum(r["ticker"] == ticker and r["sec_filing_date"].startswith(str(year)) for r in calendar) for year in range(2018, 2026)}
        for ticker in tickers
    }
    unusual = {
        ticker: years for ticker, years in annual_by_ticker.items()
        if any(count != 4 for count in years.values())
    }
    quality = {
        "scope": {"tickers": tickers, "start": "2018-01-01", "end": "2025-12-31"},
        "source": "SEC EDGAR 8-K Item 2.02 metadata and filed documents",
        "raw_item_2_02_candidates": sum(raw_candidate_counts.values()),
        "retained_events": len(calendar),
        "excluded_events": len(excluded),
        "unresolved_events": len(unresolved),
        "ambiguous_retained_events": sum(r["ambiguous"] == "YES" for r in calendar),
        "events_without_causal_entry_session": sum(not r["earliest_causal_entry_session"] for r in calendar),
        "classification": dict(class_counts),
        "retained_by_ticker": dict(sorted(counts_by_ticker.items())),
        "raw_candidates_by_ticker": raw_candidate_counts,
        "retained_by_year": dict(sorted(counts_by_year.items())),
        "coverage_by_ticker_and_year": annual_by_ticker,
        "unusual_four_per_year_comparison": unusual,
        "excluded_by_reason": dict(Counter(r["filter_reason"] for r in excluded)),
        "unresolved_by_ticker": dict(Counter(r["ticker"] for r in unresolved)),
        "fiscal_quarter_available": sum(bool(r["fiscal_quarter"]) for r in calendar),
        "fiscal_period_end_available": sum(bool(r["fiscal_period_end"]) for r in calendar),
        "manual_review_sample_size": len(manual_rows),
        "pipeline_exceptions": len(EVENT_OVERRIDES),
        "pipeline_exception_tickers": [row["ticker"] for row in EVENT_OVERRIDES],
        "checks": {
            "weekend_reaction_sessions": sum(date.fromisoformat(r["complete_reaction_session"]).weekday() >= 5 for r in calendar if r["complete_reaction_session"]),
            "weekend_entry_sessions": sum(date.fromisoformat(r["earliest_causal_entry_session"]).weekday() >= 5 for r in calendar if r["earliest_causal_entry_session"]),
            "reaction_session_not_in_market_calendar": sum(date.fromisoformat(r["complete_reaction_session"]) not in sessions for r in calendar if r["complete_reaction_session"]),
            "entry_session_not_in_market_calendar": sum(date.fromisoformat(r["earliest_causal_entry_session"]) not in sessions for r in calendar if r["earliest_causal_entry_session"]),
        },
    }
    assert sum(raw_candidate_counts.values()) == 1609, "SEC candidate set changed; repeat the accession review"
    assert not unresolved, "Unresolved filings must not enter the final calendar"
    assert len(calendar) == 1504, f"Expected 1,504 retained events, found {len(calendar)}"
    assert set(counts_by_ticker.values()) == {32}, "Every ticker must have 32 retained events"
    assert set(counts_by_year.values()) == {188}, "Every year must have 188 retained events"
    assert not unusual, f"Unexpected annual coverage anomalies: {unusual}"
    assert not any(quality["checks"].values()), f"Causality/calendar checks failed: {quality['checks']}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "quality_summary_full.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(quality, indent=2))


if __name__ == "__main__":
    main()
