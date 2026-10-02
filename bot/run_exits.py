"""Run before the close on every NYSE session to send ninth-session MOC exits."""
import json
from .broker_ibkr import IBKRPaperBroker
from .config import from_env
from .runtime import run_exits
from .storage import Store


def main():
    settings=from_env();store=Store(settings.db_path)
    broker=IBKRPaperBroker(settings) if settings.trading_mode=='PAPER' and settings.trading_enabled else None
    try:print(json.dumps(run_exits(store,settings,broker),indent=2,default=str))
    finally:
        if broker:broker.close()
        store.close()


if __name__=='__main__':main()
