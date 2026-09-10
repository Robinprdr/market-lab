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
    if frame[["Open", "High", "Low", "Close"]].isna().any().any():
        raise ValueError("OHLC contains nulls")


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
    out["Signal"] = pd.Series(signal, index=frame.index).reindex(out.index).fillna(False).astype(bool)
    out["Eligible_Signal"] = out.Signal & _eligible(out)
    grouped = out.groupby("Ticker", sort=False, group_keys=False)
    out["Signal_Date"] = out["Date"].where(out.Eligible_Signal)
    out["Entry_Date"] = grouped["Date"].shift(-entry_offset).where(out.Eligible_Signal)
    out["Entry_Open"] = grouped["Open"].shift(-entry_offset).where(out.Eligible_Signal)
    sign = 1 if direction == "LONG" else -1
    for h in horizons:
        if h < entry_offset:
            raise ValueError("horizon must include the entry offset")
        # h is expressed in sessions after signal t, matching the project's
        # Close[t+h] / Open[t+1] convention for daily signals.
        exit_date = grouped["Date"].shift(-h)
        exit_close = grouped["Close"].shift(-h)
        out[f"Exit_Date_{h}D"] = exit_date.where(out.Eligible_Signal)
        raw = exit_close / out.Entry_Open - 1
        out[f"Future_Return_{h}D"] = (sign * raw).where(out.Eligible_Signal)
    return out[out.Eligible_Signal].copy()


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
    if merged.Entry_Open.isna().any():
        raise ValueError("event entry_date is not a price session")
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
        merged[f"Future_Return_{h}D"] = sign * (merged[f"exit_close_{h}D"] / merged.Entry_Open - 1)
    return merged


def deduplicate_episodes(signals: pd.DataFrame, key: str = "Ticker", signal_date: str = "Date") -> pd.DataFrame:
    """Keep the first true row after a false row for each ticker."""
    if signals.empty:
        return signals.copy()
    x = signals.sort_values([key, signal_date]).copy()
    x["_episode_start"] = x.groupby(key, sort=False)[signal_date].diff().notna()
    # With a signal-only frame, every row is potentially true. The caller can
    # pass a complete frame with Signal=False rows to apply the strict rule.
    if "Signal" in x:
        x["_episode_start"] = x["Signal"] & ~x.groupby(key, sort=False).Signal.shift(1).fillna(False)
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


def evaluate(trades: pd.DataFrame, config: ExperimentConfig, label: str = "ALL") -> pd.DataFrame:
    rows = []
    for h in config.horizons:
        col = f"Future_Return_{h}D"
        if col not in trades:
            raise ValueError(f"missing {col}")
        gross = _stats(trades[col])
        net = trades[col] - config.costs.round_trip
        net_stats = _stats(net)
        rows.append({"Group": label, "Horizon": h, "Result": "GROSS", **gross})
        rows.append({"Group": label, "Horizon": h, "Result": "NET", **net_stats})
    return pd.DataFrame(rows)


def split_by_config(trades: pd.DataFrame, config: ExperimentConfig) -> dict[str, pd.DataFrame]:
    dates = pd.to_datetime(trades["Signal_Date"] if "Signal_Date" in trades else trades["Date"])
    out = {"ALL": trades}
    if config.train_period:
        out["TRAIN"] = trades[(dates >= config.train_period[0]) & (dates <= config.train_period[1])]
    if config.oos_period:
        out["OOS"] = trades[(dates >= config.oos_period[0]) & (dates <= config.oos_period[1])]
    return out


def walk_forward_annual(trades: pd.DataFrame, config: ExperimentConfig) -> pd.DataFrame:
    dates = pd.to_datetime(trades["Signal_Date"] if "Signal_Date" in trades else trades["Date"])
    rows = []
    for year in sorted(dates.dt.year.dropna().unique()):
        subset = trades[dates.dt.year == year]
        rows.append({"Year": int(year), **{f"{k}_{h}D": v for h in config.horizons for k, v in
                     (("N", len(subset)), ("Mean_Net", _stats(subset[f"Future_Return_{h}D"] - config.costs.round_trip)["Mean"]),
                      ("Win_Rate_Net", _stats(subset[f"Future_Return_{h}D"] - config.costs.round_trip)["Win_Rate"]))}})
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
