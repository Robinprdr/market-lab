"""Small, research-only primitives for auditable market experiments."""

from .core import (
    ExperimentConfig,
    align_daily_signals,
    align_event_signals,
    deduplicate_episodes,
    evaluate,
    split_by_config,
    walk_forward_annual,
    leave_one_stock_out,
)

__all__ = [
    "ExperimentConfig", "align_daily_signals", "align_event_signals",
    "deduplicate_episodes", "evaluate", "split_by_config", "walk_forward_annual", "leave_one_stock_out",
]
