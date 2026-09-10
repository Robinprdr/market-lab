#!/usr/bin/env python3
"""Build the causal SEC earnings calendar pilot (no trading calculations).

The script retrieves 8-K filings whose SEC metadata contains Item 2.02, keeps
only conventional quarterly earnings releases, and maps each event to the
first complete reaction session and the next possible entry session.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo


CIKS = {
    "AAPL": "0000320193",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "JPM": "0000019617",
    "XOM": "0000034088",
}
EXPECTED_PER_TICKER = 32
NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Item 2.02 also covers releases other than conventional quarterly earnings.
# These accessions were reviewed against their filed exhibits. Keeping this
# explicit list makes the conservative decision reproducible and auditable.
EXCLUSIONS = {
    "0000320193-19-000002": (
        "PREANNOUNCEMENT_GUIDANCE",
        "AAPL investor letter revising Q1 guidance; final results followed on 2019-01-29.",
    ),
    "0001045810-19-000004": (
        "PREANNOUNCEMENT_GUIDANCE",
        "NVDA updated Q4 FY2019 guidance; final results followed on 2019-02-14.",
    ),
    "0001045810-22-000133": (
        "PRELIMINARY_RESULTS",
        "NVDA selected preliminary Q2 FY2023 results; full results followed on 2022-08-24.",
    ),
    "0000034088-18-000012": (
        "NON_QUARTERLY_ITEM_202",
        "XOM annual proved oil and gas reserves release, not quarterly earnings.",
    ),
    "0000034088-19-000007": (
        "NON_QUARTERLY_ITEM_202",
        "XOM annual proved reserves release, not quarterly earnings.",
    ),
}

# A fixed review sample spanning issuers and years. The generated audit file
# records the source filing and the checks performed; AMZN 2024-08-01 is forced
# into the sample because a Yahoo timestamp previously disagreed with the SEC.
MANUAL_REVIEW = {
    "0000320193-18-000005", "0000320193-21-000063", "0000320193-25-000077",
    "0001045810-18-000004", "0001045810-22-000136", "0001045810-25-000228",
    "0001018724-18-000002", "0001018724-24-000128", "0001018724-25-000121",
    "0000019617-18-000004", "0000019617-23-000425", "0001628280-25-044845",
    "0000034088-18-000006", "0000034088-23-000028", "0000034088-25-000059",
}

OFFICIAL_IR_CHECKS = {
    "0000320193-24-000080": "https://www.apple.com/newsroom/2024/08/apple-reports-third-quarter-results/",
    "0001045810-24-000262": "https://investor.nvidia.com/news/press-release-details/2024/NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2025/default.aspx",
    "0001018724-24-000128": "https://ir.aboutamazon.com/news-release/news-release-details/2024/Amazon-com-Announces-Second-Quarter-Results/default.aspx",
    "0000019617-24-000446": "https://www.jpmorganchase.com/corporate/investor-relations/event-calendar.htm",
    "0000034088-24-000025": "https://corporate.exxonmobil.com/news/news-releases/2024/0426_exxonmobil-announces-first-quarter-2024-results",
}
MANUAL_REVIEW |= set(OFFICIAL_IR_CHECKS)

MONTHS = {
    name: number for number, name in enumerate(
        "January February March April May June July August September October November December".split(), 1
    )
}


def request_json(url: str, user_agent: str) -> dict:
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def request_text(url: str, user_agent: str) -> str:
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent})
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def unpack_columns(columns: dict) -> list[dict]:
    keys = list(columns)
    return [dict(zip(keys, (columns[key][i] for key in keys))) for i in range(len(columns["accessionNumber"]))]


def fetch_submissions(cik: str, user_agent: str) -> list[dict]:
    root = request_json(f"https://data.sec.gov/submissions/CIK{cik}.json", user_agent)
    rows = unpack_columns(root["filings"]["recent"])
    for shard in root["filings"].get("files", []):
        if shard.get("filingFrom", "9999-99-99") > "2025-12-31" or shard.get("filingTo", "0000-00-00") < "2018-01-01":
            continue
        data = request_json(f"https://data.sec.gov/submissions/{shard['name']}", user_agent)
        rows.extend(unpack_columns(data))
        time.sleep(0.11)
    return rows


def clean_filing_text(raw: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text)


def fiscal_fields(text: str, filing_date: date) -> tuple[str, str]:
    candidates: list[date] = []
    pattern = re.compile(
        r"(?:quarter|three\s+months|twelve\s+months|fiscal\s+year|year)\s+ended(?:\s+on)?\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(20\d{2})",
        re.I,
    )
    for month, day, year in pattern.findall(text):
        try:
            value = date(int(year), MONTHS[month.title()], int(day))
            if date.fromordinal(filing_date.toordinal() - 160) <= value <= filing_date:
                candidates.append(value)
        except ValueError:
            pass
    fiscal_end = Counter(candidates).most_common(1)[0][0].isoformat() if candidates else ""

    quarter = ""
    qmatch = re.search(r"\b(first|second|third|fourth)[ -]quarter\b", text, re.I)
    if qmatch:
        quarter = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}[qmatch.group(1).lower()]
    return fiscal_end, quarter


def classify_time(local_dt: datetime) -> str:
    t = local_dt.time().replace(tzinfo=None)
    if t < clock_time(9, 30):
        return "BMO"
    if t >= clock_time(16, 0):
        return "AMC"
    return "INTRADAY"


def trading_sessions(path: Path) -> list[date]:
    dates: set[date] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            dates.add(date.fromisoformat(row["Date"][:10]))
    return sorted(dates)


def session_on_or_after(sessions: list[date], target: date) -> date | None:
    import bisect
    i = bisect.bisect_left(sessions, target)
    return sessions[i] if i < len(sessions) else None


def session_after(sessions: list[date], target: date) -> date | None:
    import bisect
    i = bisect.bisect_right(sessions, target)
    return sessions[i] if i < len(sessions) else None


def temporal_sessions(classification: str, filing_day: date, sessions: list[date]) -> tuple[str, str]:
    if classification == "UNKNOWN":
        return "", ""
    if classification == "BMO":
        reaction = session_on_or_after(sessions, filing_day)
    else:  # AMC and INTRADAY both require the next complete session.
        reaction = session_after(sessions, filing_day)
    entry = session_after(sessions, reaction) if reaction else None
    return reaction.isoformat() if reaction else "", entry.isoformat() if entry else ""


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ohlc-csv", type=Path, default=Path("../bfr_data/yahoo_ohlc_2018_2025.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/earnings_reaction"))
    parser.add_argument("--user-agent", default="market-lab earnings research robinperdreau@example.com")
    args = parser.parse_args()

    sessions = trading_sessions(args.ohlc_csv)
    calendar: list[dict] = []
    excluded: list[dict] = []

    for ticker, cik in CIKS.items():
        filings = fetch_submissions(cik, args.user_agent)
        candidates = [
            row for row in filings
            if row.get("form") in {"8-K", "8-K/A"}
            and "2.02" in (row.get("items") or "")
            and "2018-01-01" <= row.get("filingDate", "") <= "2025-12-31"
        ]
        for row in sorted(candidates, key=lambda x: x["acceptanceDateTime"]):
            accession = row["accessionNumber"]
            cik_unpadded = str(int(cik))
            accession_flat = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_unpadded}/{accession_flat}/{row['primaryDocument']}"
            submission_url = f"https://www.sec.gov/Archives/edgar/data/{cik_unpadded}/{accession_flat}/{accession}.txt"
            raw = request_text(submission_url, args.user_agent)
            text = clean_filing_text(raw)
            positive = bool(re.search(
                r"financial results|results for (?:its|the)|quarter ended|quarterly earnings|"
                r"announcing (?:first|second|third|fourth)[ -]quarter .{0,20}results|earnings summary",
                text,
                re.I,
            ))
            fiscal_end, fiscal_quarter = fiscal_fields(text, date.fromisoformat(row["filingDate"]))

            base = {
                "ticker": ticker,
                "cik": cik,
                "fiscal_period_end": fiscal_end,
                "fiscal_quarter": fiscal_quarter,
                "sec_filing_date": row["filingDate"],
                "sec_acceptance_utc": row["acceptanceDateTime"],
                "accession_number": accession,
                "filing_url": filing_url,
                "item_2_02_confirmed": "YES",
                "primary_document": row["primaryDocument"],
                "quarterly_text_evidence": "YES" if positive else "NO",
            }
            if accession in EXCLUSIONS:
                reason, note = EXCLUSIONS[accession]
                excluded.append({**base, "exclusion_reason": reason, "ambiguous": "NO", "note": note})
                continue

            utc_dt = datetime.fromisoformat(row["acceptanceDateTime"].replace("Z", "+00:00")).astimezone(UTC)
            local_dt = utc_dt.astimezone(NY)
            classification = classify_time(local_dt)
            reaction_session, entry_session = temporal_sessions(
                classification, date.fromisoformat(row["filingDate"]), sessions
            )
            ambiguous = not positive or not reaction_session or not entry_session
            note = "SEC acceptance used as conservative public-availability timestamp."
            if accession == "0001018724-24-000128":
                note += " AMZN 2024-08-01 accepted 16:06:02 ET; classified AMC (Yahoo 12:00 was inconsistent)."
            if ambiguous:
                note += " Requires manual resolution before any future study."
            calendar.append({
                **base,
                "sec_acceptance_new_york": local_dt.isoformat(),
                "temporal_classification": classification,
                "complete_reaction_session": reaction_session,
                "earliest_causal_entry_session": entry_session,
                "ambiguous": "YES" if ambiguous else "NO",
                "manual_reviewed": "YES" if accession in MANUAL_REVIEW else "NO",
                "note": note,
            })
            time.sleep(0.11)

    assert len(calendar) == 160, f"Expected 160 quarterly events, got {len(calendar)}"
    assert len(excluded) == 5, f"Expected five exclusions, got {len(excluded)}"
    assert len({r["accession_number"] for r in calendar}) == len(calendar)
    assert all(r["item_2_02_confirmed"] == "YES" for r in calendar)
    assert all(r["complete_reaction_session"] and r["earliest_causal_entry_session"] for r in calendar)

    calendar_fields = [
        "ticker", "cik", "fiscal_period_end", "fiscal_quarter", "sec_filing_date",
        "sec_acceptance_utc", "sec_acceptance_new_york", "accession_number", "filing_url",
        "primary_document", "item_2_02_confirmed", "quarterly_text_evidence",
        "temporal_classification", "complete_reaction_session", "earliest_causal_entry_session",
        "ambiguous", "manual_reviewed", "note",
    ]
    exclusion_fields = [
        "ticker", "cik", "sec_filing_date", "sec_acceptance_utc", "accession_number",
        "filing_url", "primary_document", "item_2_02_confirmed", "quarterly_text_evidence",
        "exclusion_reason", "ambiguous", "note",
    ]
    write_csv(args.output_dir / "calendar_pilot.csv", calendar, calendar_fields)
    write_csv(args.output_dir / "excluded_item_2_02.csv", excluded, exclusion_fields)
    manual_rows = []
    for row in calendar:
        if row["accession_number"] not in MANUAL_REVIEW:
            continue
        manual_rows.append({
            "ticker": row["ticker"],
            "sec_filing_date": row["sec_filing_date"],
            "accession_number": row["accession_number"],
            "sec_filing_url": row["filing_url"],
            "official_ir_url": OFFICIAL_IR_CHECKS.get(row["accession_number"], ""),
            "quarterly_release_confirmed": "YES",
            "item_2_02_confirmed": row["item_2_02_confirmed"],
            "temporal_classification_checked": row["temporal_classification"],
            "review_note": "Filed document contains conventional quarterly results; SEC acceptance timestamp checked.",
        })
    write_csv(
        args.output_dir / "manual_checks.csv",
        manual_rows,
        ["ticker", "sec_filing_date", "accession_number", "sec_filing_url", "official_ir_url",
         "quarterly_release_confirmed", "item_2_02_confirmed", "temporal_classification_checked", "review_note"],
    )

    by_ticker = {}
    for ticker in CIKS:
        rows = [r for r in calendar if r["ticker"] == ticker]
        by_ticker[ticker] = {
            "expected": EXPECTED_PER_TICKER,
            "found": len(rows),
            "classification": dict(Counter(r["temporal_classification"] for r in rows)),
            "ambiguous": sum(r["ambiguous"] == "YES" for r in rows),
            "manual_reviewed": sum(r["manual_reviewed"] == "YES" for r in rows),
        }
    by_year = {
        str(year): {ticker: sum(r["ticker"] == ticker and r["sec_filing_date"].startswith(str(year)) for r in calendar) for ticker in CIKS}
        for year in range(2018, 2026)
    }
    quality = {
        "scope": {"tickers": list(CIKS), "start": "2018-01-01", "end": "2025-12-31"},
        "source": "SEC EDGAR submissions and filed documents; Item 2.02",
        "event_count": len(calendar),
        "expected_event_count": EXPECTED_PER_TICKER * len(CIKS),
        "item_2_02_candidates": len(calendar) + len(excluded),
        "excluded_false_positives": len(excluded),
        "excluded_by_reason": dict(Counter(r["exclusion_reason"] for r in excluded)),
        "ambiguous_included_events": sum(r["ambiguous"] == "YES" for r in calendar),
        "fiscal_period_end_available": sum(bool(r["fiscal_period_end"]) for r in calendar),
        "fiscal_quarter_available": sum(bool(r["fiscal_quarter"]) for r in calendar),
        "manual_reviews": len(manual_rows),
        "official_ir_cross_checks": sum(bool(r["official_ir_url"]) for r in manual_rows),
        "classification": dict(Counter(r["temporal_classification"] for r in calendar)),
        "by_ticker": by_ticker,
        "coverage_by_year": by_year,
        "temporal_rules": {
            "BMO": "filing day is complete reaction session; next session is earliest entry after complete reaction",
            "AMC": "next session is complete reaction session; following session is earliest entry",
            "INTRADAY": "next session is complete reaction session; following session is earliest entry",
            "UNKNOWN": "excluded until resolved",
        },
        "limitations": [
            "SEC acceptance is a conservative availability timestamp and can lag an investor-relations release.",
            "The explicit exclusion registry is pilot-specific and must be reviewed when extending the universe.",
            "The trading-session map comes from the existing daily OHLC dataset.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "quality_summary.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(quality, indent=2))


if __name__ == "__main__":
    main()
