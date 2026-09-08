#!/usr/bin/env python3
"""One fixed research definition; no strategy edits, parameter search or trading.

Run from repo root: python -B research/short_momentum/bearish_failed_rally_v1.py --cache-dir /tmp/market-lab-bfr-cache --output-dir /tmp/market-lab-bfr-v1
Dependencies: numpy, pandas. Yahoo chart OHLC uses the same unadjusted-Close
convention as the project's yfinance(auto_adjust=False); Adj Close is not used.
The committed core CSV supplies the evaluation dates and authoritative labels.
Raw market inputs are cached separately. Reuse --ohlc-csv for existing OHLC.

Frozen before observing outcomes:
* maximal run of 1--3 strictly rising closes ending t-1;
* Close[t-1] < SMA50[t-1], Return_10D[t-1] < 0;
* Close[t] < SMA50[t] and Close[t] < min(Low of that run);
* only the immediately following session can confirm that rebound;
* enter Open[t+1]; action return = Close[t+h]/Open[t+1]-1, h=1,3,5.
No amplitude cap, stop, target, costs or portfolio sizing. Days mean sessions.
"""

import argparse
import hashlib
import io
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

COMMIT = "34f4bbb51d9e835d4a58800d54695980bb3bd19d"
CORE_BLOB = "ce157c4630580cf431a841af42c18db627c68bee"
CORE_URL = f"https://raw.githubusercontent.com/Robinprdr/market-lab/{COMMIT}/results/short_momentum/short_momentum_v1_research_core.csv"
START, END = "2018-01-01", "2025-12-20"
HORIZONS = (1, 3, 5)


def read_url(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def yahoo_ohlc(ticker):
    p1, p2 = [int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()) for s in (START, END)]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d"
    payload = json.loads(read_url(url))
    if payload["chart"].get("error"):
        raise ValueError(payload["chart"]["error"])
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    dates = pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert(result["meta"]["exchangeTimezoneName"])
    frame = pd.DataFrame({c.title(): quote[c] for c in ("open", "high", "low", "close", "volume")})
    frame["Date"] = dates.tz_localize(None).normalize()
    frame["Ticker"] = ticker
    if frame[["Open", "High", "Low", "Close", "Volume"]].isna().any().any():
        raise ValueError(f"Missing OHLCV for {ticker}; not silently dropping sessions")
    return frame.loc[(frame.Date >= START) & (frame.Date < END)].copy()


def signal_features(frame):
    """Causal function: never reads labels, future rows, or a centered window."""
    x = frame.sort_values("Date").reset_index(drop=True).copy()
    x["Session"] = np.arange(len(x))
    for n in (1, 3, 10, 20):
        x[f"Return_{n}D"] = x.Close.pct_change(n, fill_method=None)
    x["SMA50"] = x.Close.rolling(50).mean()
    x["Distance_SMA50"] = x.Close / x.SMA50 - 1
    x["SMA20_vs_SMA50"] = x.Close.rolling(20).mean() / x.SMA50 - 1
    run, count = [], 0
    for up in x.Return_1D.gt(0):
        count = count + 1 if up else 0
        run.append(count)
    x["Rebound_Length"] = pd.Series(run).shift(1).fillna(0).astype(int)
    x["Rebound_Low"] = np.nan
    x["Rebound_Start"] = pd.NaT
    x["Rebound_End"] = x.Date.shift(1)
    for n in (1, 2, 3):
        mask = x.Rebound_Length.eq(n)
        x.loc[mask, "Rebound_Low"] = x.Low.shift(1).rolling(n).min()[mask]
        x.loc[mask, "Rebound_Start"] = x.Date.shift(n)[mask]
    x["Prior_Distance_SMA50"] = x.Distance_SMA50.shift(1)
    x["Prior_Return_10D"] = x.Return_10D.shift(1)
    x["Signal"] = (
        x.Rebound_Length.between(1, 3)
        & x.Prior_Distance_SMA50.lt(0)
        & x.Prior_Return_10D.lt(0)
        & x.Distance_SMA50.lt(0)
        & x.Close.lt(x.Rebound_Low)
    )
    return x


def self_test():
    # A weak history followed by a complete 1--4 day rebound and breakdown.
    for n in (1, 2, 3, 4):
        close = list(np.linspace(120, 90, 65)) + [90 + 0.1 * (i + 1) for i in range(n)] + [89.0]
        x = pd.DataFrame({"Date": pd.bdate_range("2020-01-01", periods=len(close)), "Close": close})
        x["Open"], x["High"], x["Low"] = x.Close, x.Close + .2, x.Close - .2
        assert bool(signal_features(x).Signal.iloc[-1]) == (n <= 3)
        if n <= 3:
            # Intraday penetration alone and exact equality are not confirmation.
            floor = x.Low.iloc[-n-1:-1].min()
            for end_close in (floor, floor + .01):
                y = x.copy()
                y.loc[len(y)-1, "Close"] = end_close
                y.loc[len(y)-1, "Low"] = floor - 1
                assert not signal_features(y).Signal.iloc[-1]
            # Removing the weak trend must remove the signal.
            y = x.copy()
            y.loc[:54, "Close"] = 50.0
            assert not signal_features(y).Signal.iloc[-1]


def independent_signal_check(x):
    """Scalar implementation verifies vectorized signal and episode boundaries."""
    c, low = x.Close.to_numpy(), x.Low.to_numpy()
    expected = np.zeros(len(x), dtype=bool)
    for i in range(50, len(x)):
        n, j = 0, i - 1
        while j > 0 and c[j] > c[j-1]:
            n += 1
            j -= 1
        if 1 <= n <= 3:
            expected[i] = (c[i-1] < c[i-50:i].mean() and c[i-1] / c[i-11] - 1 < 0
                           and c[i] < c[i-49:i+1].mean() and c[i] < low[i-n:i].min())
    assert np.array_equal(x.Signal, expected)
    # A truncated history must produce exactly the same already-observable signals.
    for cutoff in (60, len(x)//2, len(x)-5):
        prefix = signal_features(x.iloc[:cutoff][["Date", "Open", "High", "Low", "Close"]])
        assert np.array_equal(prefix.Signal, x.Signal.iloc[:cutoff])


def metrics(x, group, year="ALL"):
    rows = []
    for h in HORIZONS:
        v = x[f"Future_Return_{h}D"].dropna()
        rows.append({"Group": group, "Year": year, "Horizon": h, "Observations": len(v),
                     "Mean": v.mean(), "Median": v.median(),
                     "Negative_Fraction": v.lt(0).mean() if len(v) else np.nan})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ohlc-csv", type=Path, help="Existing Date,Ticker,Open,High,Low,Close OHLC history")
    args = parser.parse_args()
    self_test()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    core_path = args.cache_dir / "short_momentum_v1_research_core.csv"
    if not core_path.exists():
        core_path.write_bytes(read_url(CORE_URL))
    blob = core_path.read_bytes()
    assert hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest() == CORE_BLOB
    core = pd.read_csv(io.BytesIO(blob), parse_dates=["Date"])
    assert not core.duplicated(["Date", "Ticker"]).any()
    assert len(core) == 93107 and core.Ticker.nunique() == 47
    assert not core[[f"Future_Return_{h}D" for h in HORIZONS]].isna().any().any()
    tickers = sorted(core.Ticker.unique())
    raw_path = args.ohlc_csv or args.cache_dir / "yahoo_ohlc_2018_2025.csv"
    if not raw_path.exists():
        if args.ohlc_csv:
            raise FileNotFoundError(raw_path)
        frames = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(yahoo_ohlc, ticker): ticker for ticker in tickers}
            for future in as_completed(futures):
                frame = future.result()
                frames.append(frame)
                print(f"OHLC {futures[future]}: {len(frame)} sessions", flush=True)
        pd.concat(frames).sort_values(["Ticker", "Date"]).to_csv(raw_path, index=False)
        (args.cache_dir / "market_source.json").write_text(json.dumps({
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Yahoo Finance chart API, quote OHLC, Adj Close unused",
            "start": START, "end_exclusive": END, "tickers": tickers}, indent=2))
    raw = pd.read_csv(raw_path, parse_dates=["Date"])
    assert not raw.duplicated(["Date", "Ticker"]).any()
    assert set(raw.Ticker) == set(tickers)
    assert not raw[["Open", "High", "Low", "Close"]].isna().any().any()
    assert (raw[["Open", "High", "Low", "Close"]] > 0).all().all()
    assert (raw.Low <= raw[["Open", "Close"]].min(axis=1)).all()
    assert (raw.High >= raw[["Open", "Close"]].max(axis=1)).all()
    frames = []
    for ticker, group in raw.groupby("Ticker"):
        x = signal_features(group)
        independent_signal_check(x)
        # Future fields are constructed only after the causal signal is fixed.
        x["Entry_Date"] = x.Date.shift(-1)
        x["Entry_Open"] = x.Open.shift(-1)
        for h in HORIZONS:
            x[f"Future_Return_{h}D"] = x.Close.shift(-h) / x.Open.shift(-1) - 1
            x[f"Exit_Date_{h}D"] = x.Date.shift(-h)
        frames.append(x)
    enriched = pd.concat(frames, ignore_index=True)
    joined = core.merge(enriched, on=["Date", "Ticker"], how="left", validate="one_to_one", suffixes=("", "_Rebuilt"), indicator=True)
    assert joined._merge.eq("both").all()
    comparisons = ["Return_1D", "Return_3D", "Return_10D", "Return_20D", "Distance_SMA50", "SMA20_vs_SMA50"] + [f"Future_Return_{h}D" for h in HORIZONS]
    reconciliation = {}
    for col in comparisons:
        a, b = joined[col], joined[col + "_Rebuilt"]
        mismatch = ~np.isclose(a, b, rtol=1e-7, atol=1e-6, equal_nan=True)
        reconciliation[col] = {"max_abs_difference": float((a-b).abs().max()), "mismatches_over_tolerance": int(mismatch.sum()),
                               "negative_sign_disagreements": int((a.lt(0) != b.lt(0)).sum())}
    (args.output_dir / "reconciliation.json").write_text(json.dumps(reconciliation, indent=2))
    # No silent mixing of materially revised prices and committed labels.
    assert all(v["mismatches_over_tolerance"] == 0 for v in reconciliation.values()), reconciliation
    assert all(reconciliation[c]["negative_sign_disagreements"] == 0 for c in ("Distance_SMA50", "Return_10D", "Return_1D"))
    joined["Year"] = joined.Date.dt.year
    signals = joined.loc[joined.Signal].copy().sort_values(["Ticker", "Date"])
    signals["Episode_ID"] = signals.Ticker + ":" + signals.Rebound_Start.dt.strftime("%Y-%m-%d") + ":" + signals.Rebound_End.dt.strftime("%Y-%m-%d")
    assert not signals.Episode_ID.duplicated().any()
    assert (signals.Entry_Date > signals.Date).all()
    assert (signals.Close < signals.Rebound_Low).all()
    intervals = signals.groupby("Ticker").Session.diff()
    overlap = {}
    for h in HORIZONS:
        retained = 0
        for _, group in signals.groupby("Ticker"):
            last = -100000
            for session in group.Session:
                if session - last >= h:
                    retained += 1
                    last = session
        overlap[str(h)] = {"pairs_overlapping_previous_signal": int(intervals.lt(h).sum()),
                           "signals_retained_one_position_per_ticker": retained}
    stats = metrics(joined, "BASELINE_GLOBAL") + metrics(signals, "BFR_V1")
    for year in sorted(joined.Year.unique()):
        stats += metrics(joined[joined.Year.eq(year)], "BASELINE_GLOBAL", int(year))
        stats += metrics(signals[signals.Year.eq(year)], "BFR_V1", int(year))
    stats = pd.DataFrame(stats)
    stats.to_csv(args.output_dir / "statistics.csv", index=False)
    counts = joined.groupby("Year").size().rename("Baseline_Observations").to_frame()
    counts["Signals"] = signals.groupby("Year").size().reindex(counts.index, fill_value=0)
    counts["Tickers"] = signals.groupby("Year").Ticker.nunique().reindex(counts.index, fill_value=0)
    counts["Dates"] = signals.groupby("Year").Date.nunique().reindex(counts.index, fill_value=0)
    counts.to_csv(args.output_dir / "annual_counts.csv")
    keep = ["Date", "Ticker", "Episode_ID", "Rebound_Start", "Rebound_End", "Rebound_Length", "Rebound_Low", "Open", "High", "Low", "Close", "SMA50", "Prior_Distance_SMA50", "Prior_Return_10D", "Session", "Entry_Date", "Entry_Open"]
    keep += [f"Future_Return_{h}D" for h in HORIZONS] + [f"Exit_Date_{h}D" for h in HORIZONS]
    signals[keep].to_csv(args.output_dir / "signals.csv", index=False)
    summary = {"commit": COMMIT, "core_git_blob": CORE_BLOB, "ohlc_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
               "baseline_rows": len(joined), "baseline_first_date": str(joined.Date.min().date()), "baseline_last_date": str(joined.Date.max().date()),
               "signals": len(signals), "mean_signals_per_year": len(signals)/joined.Year.nunique(),
               "tickers": int(signals.Ticker.nunique()), "dates": int(signals.Date.nunique()),
               "first_signal": str(signals.Date.min().date()) if len(signals) else None,
               "last_signal": str(signals.Date.max().date()) if len(signals) else None,
               "rebound_length_counts": signals.Rebound_Length.value_counts().sort_index().to_dict(),
               "duplicate_episode_ids": int(signals.Episode_ID.duplicated().sum()), "consecutive_same_ticker_signals": int(intervals.eq(1).sum()),
               "holding_overlap": overlap, "checks": "synthetic boundaries, scalar equivalence, prefix invariance, OHLC integrity, core reconciliation passed"}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(stats[stats.Year.eq("ALL")].to_string(index=False))
    print(counts.to_string())
    print(stats[stats.Group.eq("BFR_V1") & ~stats.Year.eq("ALL")].to_string(index=False))


if __name__ == "__main__":
    main()
