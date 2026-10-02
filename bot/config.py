"""Environment configuration. LIVE is deliberately unsupported in V1."""
from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    trading_mode: str = 'PAPER'
    trading_enabled: bool = False
    allowed_account_id: str = ''
    ibkr_host: str = '127.0.0.1'
    ibkr_port: int = 7497
    ibkr_client_id: int = 71
    db_path: Path = ROOT/'data/cache/bot_core/market_lab.sqlite'
    initial_equity_usd: float = 10000.
    weight_per_entry: float = .10
    max_positions: int = 5
    max_exposure_per_ticker: float = .10
    max_total_exposure: float = .50
    max_order_notional_usd: float = 1000.
    max_orders_per_day: int = 5
    max_entry_price_drift: float = .03

    def validate(self):
        if self.trading_mode not in ('DRY_RUN','PAPER'):
            raise ValueError('LIVE trading is not implemented; use DRY_RUN or PAPER')
        if self.trading_mode == 'PAPER':
            if (self.trading_enabled or self.allowed_account_id) and not self.allowed_account_id.startswith('DU'):
                raise ValueError('IBKR_ALLOWED_ACCOUNT_ID must identify one explicit DU paper account')
            if self.ibkr_host not in ('127.0.0.1','localhost','::1') or self.ibkr_port not in (7497,4002):
                raise ValueError('Only local TWS/IB Gateway paper ports are permitted')
            if self.ibkr_client_id <= 0:
                raise ValueError('Use a dedicated nonzero IBKR client ID')
        if not (0 < self.weight_per_entry <= self.max_exposure_per_ticker <= 1):
            raise ValueError('Invalid position sizing')
        if not (0 < self.max_total_exposure <= 1) or self.max_positions < 1 or self.max_orders_per_day < 1:
            raise ValueError('Invalid risk limits')
        if self.initial_equity_usd <= 0 or self.max_order_notional_usd <= 0 or not (0 <= self.max_entry_price_drift <= .20):
            raise ValueError('Invalid capital or price guard')
        return self


def from_env():
    cfg = Settings(
        trading_mode=os.getenv('TRADING_MODE','PAPER').upper(),
        trading_enabled=os.getenv('TRADING_ENABLED','false').lower() == 'true',
        allowed_account_id=os.getenv('IBKR_ALLOWED_ACCOUNT_ID','').strip(),
        ibkr_host=os.getenv('IBKR_HOST','127.0.0.1'),
        ibkr_port=int(os.getenv('IBKR_PORT','7497')),
        ibkr_client_id=int(os.getenv('IBKR_CLIENT_ID','71')),
        db_path=Path(os.getenv('BOT_DB_PATH',str(Settings.db_path))),
        initial_equity_usd=float(os.getenv('BOT_INITIAL_EQUITY_USD','10000')),
        weight_per_entry=float(os.getenv('BOT_WEIGHT_PER_ENTRY','0.10')),
        max_positions=int(os.getenv('BOT_MAX_POSITIONS','5')),
        max_exposure_per_ticker=float(os.getenv('BOT_MAX_EXPOSURE_PER_TICKER','0.10')),
        max_total_exposure=float(os.getenv('BOT_MAX_TOTAL_EXPOSURE','0.50')),
        max_order_notional_usd=float(os.getenv('BOT_MAX_ORDER_NOTIONAL_USD','1000')),
        max_orders_per_day=int(os.getenv('BOT_MAX_ORDERS_PER_DAY','5')),
        max_entry_price_drift=float(os.getenv('BOT_MAX_ENTRY_PRICE_DRIFT','0.03')),
    )
    return cfg.validate()
