"""Generic, deterministic research primitives.

This module deliberately has no optimizer, broker, portfolio allocator, or
live execution path. A signal is a row-level assertion; a trade is a retained
entry/exit observation after the configured episode rule is applied.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    entry_fee: float = 0.0005
    entry_slippage: float = 0.0005
    exit_fee: float = 0.0005
    exit_slippage: float = 0.0005

    @property
    def round_trip(self) -> float:
        return self.entry_fee + self.entry_slippage + self.exit_fee + self.exit_slippage


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_name: str
    research_stage: str
    direction: str
    signal_timing: str
    entry_rule: str
    horizons: tuple[int, ...] = (1, 3, 5)
    costs: Costs = field(default_factory=Costs)
    episode_rule: str = "none"
    train_period: tuple[str, str] | None = None
    oos_period: tuple[str, str] | None = None
    walk_forward_rule: str = "annual, fixed rules, no shuffle"
    universe: str = "provided frame / optional Eligible[ticker,date]"

    def __post_init__(self) -> None:
        if self.research_stage not in {"EXPLORATORY", "CANDIDATE", "VALIDATION"}:
            raise ValueError("research_stage must be EXPLORATORY, CANDIDATE, or VALIDATION")
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if not self.horizons or any(h < 1 for h in self.horizons):
            raise ValueError("horizons must be positive")

    def as_dict(self) -> dict:
        value = asdict(self)
        value["costs"] = asdict(self.costs)
        value["horizons"] = list(self.horizons)
        return value


def _validate_ohlc(frame: pd.DataFrame) -> None:
    required = {"Date", "Ticker", "Open", "High", "Low", "Close", "Volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if frame.duplicated(["Ticker", "Date"]).any():
        raise ValueError("duplicate ticker/date rows")
    # Missing prices are retained as explicit diagnostics. They must not be
    # silently removed before signal/entry/exit accounting.


def _eligible(frame: pd.DataFrame) -> pd.Series:
    if "Eligible" not in frame:
        return pd.Series(True, index=frame.index)
    return frame["Eligible"].fillna(False).astype(bool)


def align_daily_signals(frame: pd.DataFrame, signal: pd.Series | Iterable[bool],
                        horizons: Iterable[int] = (1, 3, 5),
                        direction: str = "LONG", entry_offset: int = 1) -> pd.DataFrame:
    """Create auditable daily trades: signal t -> Open[t+entry_offset]."""
    _validate_ohlc(frame)
    if entry_offset < 1 or direction not in {"LONG", "SHORT"}:
        raise ValueError("daily entry_offset must be >= 1 and direction valid")
    out = frame.sort_values(["Ticker", "Date"]).copy()
    supplied = pd.Series(signal, index=frame.index).reindex(out.index)
    if supplied.isna().any():
        raise ValueError("signal must contain one non-null boolean per row")
    out["Signal"] = supplied.astype(bool)
    out["Signal_Eligible"] = out.Signal & _eligible(out)
    grouped = out.groupby("Ticker", sort=False, group_keys=False)
    out["Signal_Date"] = out["Date"].where(out.Signal_Eligible)
    out["Entry_Date"] = grouped["Date"].shift(-entry_offset).where(out.Signal_Eligible)
    out["Entry_Open"] = grouped["Open"].shift(-entry_offset).where(out.Signal_Eligible)
    next_eligible = grouped["Eligible"].shift(-entry_offset).fillna(True).astype(bool) if "Eligible" in out else pd.Series(True, index=out.index)
    out["Entry_Eligible"] = out.Signal_Eligible & next_eligible
    out["Entry_Valid"] = out.Entry_Eligible & out.Entry_Open.notna()
    sign = 1 if direction == "LONG" else -1
    for h in horizons:
        if h < entry_offset:
            raise ValueError("horizon must include the entry offset")
        # h is expressed in sessions after signal t, matching the project's
        # Close[t+h] / Open[t+1] convention for daily signals.
        exit_date = grouped["Date"].shift(-h)
        exit_close = grouped["Close"].shift(-h)
        out[f"Exit_Date_{h}D"] = exit_date.where(out.Signal_Eligible)
        raw = exit_close / out.Entry_Open - 1
        out[f"Exit_Close_{h}D"] = exit_close.where(out.Signal_Eligible)
        out[f"Future_Return_{h}D"] = (sign * raw).where(out.Signal_Eligible & out.Entry_Valid)
        out[f"Return_Evaluable_{h}D"] = out.Signal_Eligible & out.Entry_Valid & exit_close.notna()
    # Keep every detected signal, including ineligible/missing-price rows, so
    # diagnostics can account for each exclusion explicitly.
    return out[out.Signal].copy()


def align_event_signals(events: pd.DataFrame, price: pd.DataFrame,
                        direction: str = "LONG", horizons: Iterable[int] = (1, 3, 5)) -> pd.DataFrame:
    """Align events to explicit entry dates; no Open[t+1] assumption."""
    required = {"ticker", "event_date", "entry_date"}
    if not required.issubset(events.columns):
        raise ValueError(f"events require {sorted(required)}")
    _validate_ohlc(price)
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    p = price.sort_values(["Ticker", "Date"]).copy()
    p["Date"] = pd.to_datetime(p.Date)
    e = events.copy()
    e["event_date"] = pd.to_datetime(e.event_date)
    e["entry_date"] = pd.to_datetime(e.entry_date)
    merged = e.merge(p.rename(columns={"Ticker": "ticker", "Date": "entry_date", "Open": "Entry_Open"}),
                     on=["ticker", "entry_date"], how="left", validate="one_to_one")
    # Missing event entries are retained and diagnosed, never silently dropped.
    sign = 1 if direction == "LONG" else -1
    # Use the issuer's observed session index, rather than calendar-day
    # arithmetic (which would fail on weekends and holidays).
    p = p.sort_values(["Ticker", "Date"])
    p["_session"] = p.groupby("Ticker").cumcount()
    merged = merged.merge(p[["Ticker", "Date", "_session"]].rename(columns={"Ticker":"ticker", "Date":"entry_date", "_session":"_entry_session"}), on=["ticker", "entry_date"], how="left", validate="one_to_one")
    for h in horizons:
        exits = p[["Ticker", "_session", "Date", "Close"]].rename(columns={"Ticker":"ticker", "_session":"_exit_session", "Date":f"exit_date_{h}D", "Close":f"exit_close_{h}D"})
        exits["_exit_session"] -= h - 1
        merged = merged.merge(exits, left_on=["ticker", "_entry_session"], right_on=["ticker", "_exit_session"], how="left", validate="one_to_one")
        merged[f"Exit_Close_{h}D"] = merged[f"exit_close_{h}D"]
        merged[f"Future_Return_{h}D"] = sign * (merged[f"exit_close_{h}D"] / merged.Entry_Open - 1)
        merged[f"Return_Evaluable_{h}D"] = merged[f"exit_close_{h}D"].notna()
    merged["Signal_Date"] = merged.event_date
    merged["Entry_Date"] = merged.entry_date
    merged["Signal_Eligible"] = merged.get("eligible", True)
    merged["Entry_Eligible"] = merged.get("entry_eligible", True)
    merged["Entry_Valid"] = merged.Signal_Eligible & merged.Entry_Eligible & merged.Entry_Open.notna()
    return merged


def deduplicate_episodes(signals: pd.DataFrame, key: str = "Ticker", signal_date: str = "Date") -> pd.DataFrame:
    """Keep episode starts from a complete chronological boolean frame.

    A signal-only frame cannot reveal where an episode ended. It is rejected
    when it contains no explicit false boundary for a ticker.
    """
    if signals.empty:
        return signals.copy()
    if "Signal" not in signals.columns:
        raise ValueError("deduplicate_episodes requires a complete frame with Signal=True/False rows")
    if signals["Signal"].isna().any() or not signals["Signal"].map(lambda v: isinstance(v, (bool, np.bool_))).all():
        raise ValueError("Signal must be non-null boolean")
    x = signals.sort_values([key, signal_date]).copy()
    if x.groupby(key).Signal.apply(lambda z: bool(z.all())).any():
        raise ValueError("cannot infer episode boundary for a ticker without an explicit Signal=False row")
    x["_episode_start"] = x["Signal"] & ~x.groupby(key, sort=False).Signal.shift(1).fillna(False).astype(bool)
    return x[x._episode_start].drop(columns="_episode_start")


def _stats(x: pd.Series) -> dict:
    x = pd.to_numeric(x, errors="coerce").dropna()
    wins = x[x > 0]
    losses = x[x < 0]
    gross_gain, gross_loss = wins.sum(), -losses.sum()
    return {
        "N": int(x.size), "Mean": float(x.mean()) if len(x) else None,
        "Median": float(x.median()) if len(x) else None,
        "Win_Rate": float((x > 0).mean()) if len(x) else None,
        "Expectancy": float(x.mean()) if len(x) else None,
        "Sum_Gains": float(gross_gain), "Sum_Losses": float(-gross_loss),
        "Profit_Factor": float(gross_gain / gross_loss) if gross_loss else None,
        "Min": float(x.min()) if len(x) else None, "Max": float(x.max()) if len(x) else None,
        "Std": float(x.std(ddof=1)) if len(x) > 1 else None,
    }


def execution_return(entry_open: pd.Series, exit_close: pd.Series, direction: str, costs: Costs) -> pd.Series:
    """Exact round-trip execution return, including fees and slippage.

    LONG: ``Close*(1-exit_slippage)*(1-exit_fee) /
    [Open*(1+entry_slippage)*(1+entry_fee)] - 1``.
    SHORT reverses both execution directions: proceeds at entry divided by
    cover cost at exit, minus one. Zero costs therefore equal the signed gross
    action return exactly.
    """
    if direction == "LONG":
        return (exit_close * (1-costs.exit_slippage) * (1-costs.exit_fee) /
                (entry_open * (1+costs.entry_slippage) * (1+costs.entry_fee)) - 1)
    if direction == "SHORT":
        return (entry_open * (1-costs.entry_slippage) * (1-costs.entry_fee) /
                (exit_close * (1+costs.exit_slippage) * (1+costs.exit_fee)) - 1)
    raise ValueError("direction must be LONG or SHORT")


def diagnostics(trades: pd.DataFrame, config: ExperimentConfig) -> dict:
    signal_eligible = trades.get("Signal_Eligible", pd.Series(True, index=trades.index)).fillna(False).astype(bool)
    entry_valid = trades.get("Entry_Valid", pd.Series(False, index=trades.index)).fillna(False).astype(bool)
    result = {"signals_detected": int(len(trades)), "entries_valid": int(entry_valid.sum()),
              "dropped_missing_entry": int((signal_eligible & ~entry_valid).sum()),
              "dropped_missing_exit": {}, "returns_evaluable": {}, "purged_period_boundary": {}}
    for h in config.horizons:
        col=f"Future_Return_{h}D"; result["returns_evaluable"][str(h)] = int(trades[col].notna().sum()) if col in trades else 0
        result["dropped_missing_exit"][str(h)] = int((trades.get(f"Exit_Close_{h}D", pd.Series(index=trades.index)).isna() & entry_valid).sum())
        result["purged_period_boundary"][str(h)] = int(trades.get(f"Purged_Period_Boundary_{h}D", pd.Series(False,index=trades.index)).sum())
    return result


def build_baseline(frame: pd.DataFrame, config: ExperimentConfig) -> pd.DataFrame:
    """Build an all-eligible daily baseline on the identical input universe."""
    signal = pd.Series(True, index=frame.index)
    baseline = align_daily_signals(frame, signal, config.horizons, config.direction)
    baseline.attrs["baseline_universe"] = tuple(sorted(frame.Ticker.dropna().unique()))
    baseline.attrs["baseline_direction"] = config.direction
    return baseline


def compare_baseline(signals: pd.DataFrame, baseline: pd.DataFrame, config: ExperimentConfig) -> pd.DataFrame:
    """Compare only samples with matching direction, dates and universes."""
    if baseline.attrs.get("baseline_direction", config.direction) != config.direction:
        raise ValueError("baseline direction differs from experiment")
    if set(signals.Ticker.dropna().unique()) - set(baseline.Ticker.dropna().unique()):
        raise ValueError("baseline universe does not cover signal universe")
    if signals.empty or baseline.empty:
        raise ValueError("cannot compare empty baseline")
    sdates = pd.to_datetime(signals.Signal_Date if "Signal_Date" in signals else signals.Date)
    bdates = pd.to_datetime(baseline.Signal_Date if "Signal_Date" in baseline else baseline.Date)
    if sdates.min() < bdates.min() or sdates.max() > bdates.max():
        raise ValueError("baseline period does not cover signal period")
    rows=[]
    for h in config.horizons:
        s=signals[f"Future_Return_{h}D"].dropna(); b=baseline.loc[bdates.between(sdates.min(),sdates.max()),f"Future_Return_{h}D"].dropna()
        if len(b)==0: raise ValueError("baseline has no evaluable rows in signal period")
        rows.extend([{"Group":"SIGNALS","Horizon":h,**_stats(s)},{"Group":"BASELINE","Horizon":h,**_stats(b)}])
    return pd.DataFrame(rows)


def evaluate(trades: pd.DataFrame, config: ExperimentConfig, label: str = "ALL") -> pd.DataFrame:
    rows = []
    for h in config.horizons:
        col = f"Future_Return_{h}D"
        if col not in trades:
            raise ValueError(f"missing {col}")
        gross = _stats(trades[col])
        if {"Entry_Open", f"Exit_Close_{h}D"}.issubset(trades.columns):
            net = execution_return(trades.Entry_Open, trades[f"Exit_Close_{h}D"], config.direction, config.costs)
        else:
            raise ValueError("exact cost calculation requires Entry_Open and Exit_Close_hD")
        net_stats = _stats(net)
        diag = diagnostics(trades, config)
        common = {"Signals_Detected": diag["signals_detected"], "Entries_Valid": diag["entries_valid"], "Returns_Evaluable": diag["returns_evaluable"][str(h)], "Dropped_Missing_Entry": diag["dropped_missing_entry"], "Dropped_Missing_Exit": diag["dropped_missing_exit"][str(h)], "Purged_Period_Boundary": diag["purged_period_boundary"][str(h)]}
        rows.append({"Group": label, "Horizon": h, "Result": "GROSS", **common, **gross})
        rows.append({"Group": label, "Horizon": h, "Result": "NET", **common, **net_stats})
    return pd.DataFrame(rows)


def split_by_config(trades: pd.DataFrame, config: ExperimentConfig) -> dict[str, pd.DataFrame]:
    dates = pd.to_datetime(trades["Signal_Date"] if "Signal_Date" in trades else trades["Date"])
    out = {"ALL": trades}
    def period(start: str, end: str) -> pd.DataFrame:
        x = trades[(dates >= start) & (dates <= end)].copy()
        for h in config.horizons:
            exit_dates = pd.to_datetime(x.get(f"Exit_Date_{h}D", pd.Series(pd.NaT, index=x.index)), errors="coerce")
            purge = exit_dates.notna() & (exit_dates > pd.Timestamp(end))
            x[f"Purged_Period_Boundary_{h}D"] = purge
            x.loc[purge, f"Future_Return_{h}D"] = np.nan
            if f"Exit_Close_{h}D" in x:
                x.loc[purge, f"Exit_Close_{h}D"] = np.nan
            x[f"Return_Evaluable_{h}D"] = x[f"Future_Return_{h}D"].notna()
        x.attrs["diagnostics"] = diagnostics(x, config)
        return x
    if config.train_period: out["TRAIN"] = period(*config.train_period)
    if config.oos_period: out["OOS"] = period(*config.oos_period)
    return out


def walk_forward_annual(trades: pd.DataFrame, config: ExperimentConfig, train_years: int = 3) -> pd.DataFrame:
    """Evaluate each test year after an explicit rolling train window."""
    if train_years < 1: raise ValueError("train_years must be positive")
    dates = pd.to_datetime(trades["Signal_Date"] if "Signal_Date" in trades else trades["Date"])
    years = sorted(dates.dt.year.dropna().unique())
    rows = []
    for i, year in enumerate(years):
        if i < train_years: continue
        train_start, train_end = int(years[i-train_years]), int(years[i-1])
        test = trades[dates.dt.year == year].copy()
        for h in config.horizons:
            if f"Exit_Date_{h}D" in test:
                purge = pd.to_datetime(test[f"Exit_Date_{h}D"]) > pd.Timestamp(f"{year}-12-31")
                test.loc[purge, f"Future_Return_{h}D"] = np.nan
                if f"Exit_Close_{h}D" in test: test.loc[purge, f"Exit_Close_{h}D"] = np.nan
        row={"Train_Start":train_start,"Train_End":train_end,"Test_Year":int(year),"Train_N":int(((dates.dt.year>=train_start)&(dates.dt.year<=train_end)).sum()),"Test_N":len(test)}
        for h in config.horizons:
            net=execution_return(test.Entry_Open,test[f"Exit_Close_{h}D"],config.direction,config.costs)
            row[f"Test_Mean_Net_{h}D"]=_stats(net)["Mean"]; row[f"Test_Win_Rate_Net_{h}D"]=_stats(net)["Win_Rate"]
        rows.append(row)
    return pd.DataFrame(rows)


def concentration(trades: pd.DataFrame, config: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    ticker_rows, year_rows, summary = [], [], {}
    year = pd.to_datetime(trades["Signal_Date"] if "Signal_Date" in trades else trades["Date"]).dt.year
    for h in config.horizons:
        col = f"Future_Return_{h}D"; net = trades[col] - config.costs.round_trip
        t = net.groupby(trades["Ticker"]).agg(["size", "mean", "sum"]).sort_values("sum", ascending=False)
        y = net.groupby(year).agg(["size", "mean", "sum"]).sort_values("sum", ascending=False)
        for name, row in t.iterrows(): ticker_rows.append({"Horizon":h,"Ticker":name,"N":int(row['size']),"Mean_Net":row['mean'],"Contribution_Net":row['sum']})
        for name, row in y.iterrows(): year_rows.append({"Horizon":h,"Year":int(name),"N":int(row['size']),"Mean_Net":row['mean'],"Contribution_Net":row['sum']})
        removals=[]
        for n in (1,3,5):
            drop=list(t.index[:n]); rest=net[~trades.Ticker.isin(drop)]
            removals.append({"count":n,"tickers":drop,"remaining_n":len(rest),"remaining_mean_net":float(rest.mean()) if len(rest) else None})
        total=net.sum(); summary[str(h)]={"best_ticker":str(t.index[0]) if len(t) else None,"best_ticker_share":float(t.iloc[0]['sum']/total) if len(t) and total else None,"best_year":int(y.index[0]) if len(y) else None,"best_year_share":float(y.iloc[0]['sum']/total) if len(y) and total else None,"remove_best":removals}
    return pd.DataFrame(ticker_rows), pd.DataFrame(year_rows), summary


def leave_one_stock_out(trades: pd.DataFrame, config: ExperimentConfig) -> pd.DataFrame:
    """Return each ticker's result when that ticker is removed."""
    rows = []
    for ticker in sorted(trades.Ticker.dropna().unique()):
        rest = trades[trades.Ticker != ticker]
        for h in config.horizons:
            s = _stats(rest[f"Future_Return_{h}D"] - config.costs.round_trip)
            rows.append({"Removed_Ticker": ticker, "Horizon": h, "Remaining_N": len(rest), "Mean_Net": s["Mean"], "Win_Rate_Net": s["Win_Rate"]})
    return pd.DataFrame(rows)
