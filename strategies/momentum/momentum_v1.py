"""
Momentum V1 - Frozen Strategy Specification

STATUS:
    FROZEN / RESEARCH COMPLETE

OBJECTIVE:
    Short-term long-only momentum based on high volatility/amplitude
    combined with strong recent momentum.

SIGNAL:
    ATR_Pct >= rolling 3-year Q80 threshold
    AND
    Return_10D >= rolling 3-year Q80 threshold

THRESHOLDS:
    Computed using only the previous 3 years of data.
    Recalculated annually.
    No future data is used.

EXECUTION:
    Signal evaluated at daily close.
    Entry at next day's open.

EXIT:
    Maximum holding period: 3 trading days.
    No SL/TP in V1.

PORTFOLIO BENCHMARK:
    Initial capital: $10,000
    Position size: 15% of current equity
    Maximum simultaneous positions: 5
    Long-only

COST MODEL:
    Buy fee: 0.05%
    Sell fee: 0.05%
    Buy slippage: 0.05%
    Sell slippage: 0.05%
    Approximate round trip cost: 0.20%

IMPORTANT:
    The 15% position size is a temporary benchmark only.
    Final portfolio-level sizing will be designed after all strategies
    have been developed and validated.

FROZEN RESEARCH CONCLUSION:
    ATR_Pct is the strongest individual factor.
    Return_10D adds useful information.
    Their combination is robust in walk-forward testing.
    Consecutive up-days were tested and rejected.
    Complex ranking scores were tested and rejected for V1.
    No obvious SPY regime filter is required.
    Universe concentration was tested and the strategy remained positive
    after removing the strongest contributors.

NEXT PHASE:
    Do not optimize Momentum V1 further.
    Develop the next independent strategy.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MomentumV1Config:
    holding_days: int = 3
    position_size: float = 0.15
    max_positions: int = 5

    atr_quantile: float = 0.80
    return_10d_quantile: float = 0.80
    training_years: int = 3

    buy_fee: float = 0.0005
    sell_fee: float = 0.0005
    buy_slippage: float = 0.0005
    sell_slippage: float = 0.0005

    long_only: bool = True


CONFIG = MomentumV1Config()
