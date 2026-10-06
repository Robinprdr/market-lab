"""Small boundary objects shared by strategy, portfolio and broker."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    ticker: str
    signal_date: str
    entry_date: str
    exit_date: str
    reference_close: float
    reason: str
    holding_sessions: int


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    strategy_id: str
    ticker: str
    side: str
    quantity: int
    intended_entry_date: str
    reason: str
    timestamp_utc: str
    expected_holding_sessions: int
    target_exit_date: str
    order_type: str
    limit_price: float | None
    account_id: str
    reference_close: float


@dataclass(frozen=True)
class BrokerPosition:
    ticker: str
    quantity: int
    market_value: float


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: int
    intent_id: str
    ticker: str
    side: str
    quantity: int
    status: str
    account_id: str


@dataclass(frozen=True)
class BrokerExecution:
    execution_id: str
    broker_order_id: int
    ticker: str
    side: str
    quantity: int
    price: float
    session: str
    account_id: str


@dataclass(frozen=True)
class BrokerSnapshot:
    account_id: str
    available_cash: float
    positions: dict[str,BrokerPosition] = field(default_factory=dict)
    open_orders: tuple[BrokerOrder,...] = ()
    executions: tuple[BrokerExecution,...] = ()
    total_cash: float | None = None
    net_liquidation: float | None = None
    account_currency: str | None = None
    cash_by_currency: dict[str,float] = field(default_factory=dict)
    available_cash_by_currency: dict[str,float] = field(default_factory=dict)
    settled_cash_by_currency: dict[str,float] = field(default_factory=dict)
    verified_cash_by_currency: dict[str,float] = field(default_factory=dict)
    account_values: dict[str,dict[str,str]] = field(default_factory=dict)


class Broker(Protocol):
    def snapshot(self,account_id: str) -> BrokerSnapshot: ...
    def submit(self,intent: OrderIntent) -> int: ...
    def close(self): ...
