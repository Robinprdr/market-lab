"""Small, research-only primitives for auditable market experiments."""

from .core import (
    Costs,
    ExperimentConfig,
    align_daily_signals,
    align_event_signals,
    deduplicate_episodes,
    evaluate,
    execution_return,
    build_baseline,
    compare_baseline,
    split_by_config,
    walk_forward_annual,
    leave_one_stock_out,
)

__all__ = [
    "Costs", "ExperimentConfig", "align_daily_signals", "align_event_signals",
    "deduplicate_episodes", "evaluate", "execution_return", "build_baseline", "compare_baseline",
    "split_by_config", "walk_forward_annual", "leave_one_stock_out",
]
