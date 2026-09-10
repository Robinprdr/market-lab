# Market Lab Research Engine V1

Research Engine is a small, deterministic layer for falsifying hypotheses. It produces signal studies; it is not a portfolio backtest and has no broker, live execution, leverage, allocator, optimizer, machine learning, or automatic feature selection.

An `ExperimentConfig` records the experiment name, stage (`EXPLORATORY`, `CANDIDATE`, or `VALIDATION`), direction, signal and entry rules, horizons, explicit costs, episode policy, train/OOS periods, walk-forward rule, and universe description. Daily experiments use `align_daily_signals`: a signal at `t` is entered at `Open[t+1]`. Event experiments use `align_event_signals` with explicit event and entry dates, so they do not assume a daily offset.

Every alignment checks required OHLCV fields, duplicate ticker/date rows, eligibility, and session-based exits. Missing entry or exit prices remain visible in diagnostic columns and are counted rather than silently discarded. The returned rows contain signal, entry, exit, and future-return columns. `evaluate` reports gross and net mean, median, win rate, expectancy, gains, losses, profit factor, distribution bounds, and sample diagnostics. `split_by_config` purges each horizon whose exit crosses a train/OOS boundary. `concentration`, `walk_forward_annual`, and `leave_one_stock_out` provide ticker/year concentration, fixed temporal windows, and per-ticker removal views. Episode de-duplication requires the caller to pass the complete chronological frame with `complete=True`; signal-only subsets are rejected, while an all-True complete episode keeps its first row.

The engine never searches thresholds or chooses a period from results. Put all rules and periods in the configuration before reading results. Costs are configurable; the default research-final model is 0.05% each for entry fee, entry slippage, exit fee, and exit slippage, while exploratory studies may explicitly set all four to zero. Returns use entry notional as the base: `gross_stock = Exit / Entry - 1`, `gross_directional = gross_stock` for LONG and `-gross_stock` for SHORT, then `net = gross_directional - (entry_fee + entry_slippage + exit_fee + exit_slippage)`. Thus zero costs exactly reproduce the corresponding signed `Future_Return` for both directions.

## Example

```python
from research.research_engine import ExperimentConfig, align_daily_signals, evaluate
cfg = ExperimentConfig(
    experiment_name="my_fixed_test", research_stage="EXPLORATORY",
    direction="LONG", signal_timing="close[t]",
    entry_rule="Open[t+1]", horizons=(1, 3, 5),
)
trades = align_daily_signals(frame, frame["MySignal"], cfg.horizons, cfg.direction)
report = evaluate(trades, cfg)
```

Run the Breakout A reproduction from the repository root:

```bash
python research/research_engine/run_breakout_a.py \
  --ohlc-csv ../bfr_data/yahoo_ohlc_2018_2025.csv
```

The standard outputs are `config.json`, `summary.json`, `statistics.csv`, `annual_statistics.csv`, `period_statistics.csv`, and `ticker_concentration.csv`; walk-forward and other diagnostics are added when requested. `requirements-research.txt` is the minimal install manifest.

Tests use synthetic OHLCV data and cover daily and event alignment, LONG/SHORT signs, 1D/3D/5D session horizons, exact costs and profit factor, episode de-duplication, train/OOS purge, true rolling walk-forward windows, baseline direction/period validation, eligibility, missing entry/exit, end-of-history, and look-ahead invariance. A signal is an observation; an entry/trade is an observation retained after the configured episode and horizon rules.
