# Market Lab Research Engine V1

Research Engine is a small, deterministic layer for falsifying hypotheses. It produces signal studies; it is not a portfolio backtest and has no broker, live execution, leverage, allocator, optimizer, machine learning, or automatic feature selection.

An `ExperimentConfig` records the experiment name, stage (`EXPLORATORY`, `CANDIDATE`, or `VALIDATION`), direction, signal and entry rules, horizons, explicit costs, episode policy, train/OOS periods, walk-forward rule, and universe description. Daily experiments use `align_daily_signals`: a signal at `t` is entered at `Open[t+1]`. Event experiments use `align_event_signals` with explicit event and entry dates, so they do not assume a daily offset.

Every alignment checks required OHLCV fields, duplicate ticker/date rows, eligibility, and session-based exits. The returned rows contain signal, entry, exit, and future-return columns. `evaluate` reports gross and net mean, median, win rate, expectancy, gains, losses, profit factor, and distribution bounds. `concentration`, `split_by_config`, and `walk_forward_annual` provide ticker/year concentration, fixed train/OOS splits, and annual walk-forward views. Episode de-duplication is explicit and never silently applied.

The engine never searches thresholds or chooses a period from results. Put all rules and periods in the configuration before reading results. Costs are configurable; the default research-final model is 0.05% each for entry fee, entry slippage, exit fee, and exit slippage, while exploratory studies may explicitly set all four to zero.

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

Tests use synthetic OHLCV data and cover daily and event alignment, LONG/SHORT signs, 1D/3D/5D session horizons, costs, profit factor, episode de-duplication, train/OOS boundaries, annual exits, and look-ahead invariance. A signal is an observation; an entry/trade is an observation retained after the configured episode and horizon rules.
