"""Read only from the allowlisted IBKR account, then reconcile local ledger."""
import json
from .broker_ibkr import IBKRPaperBroker
from .config import from_env
from .runtime import run_reconcile
from .storage import Store


def main():
    settings=from_env();store=Store(settings.db_path);broker=IBKRPaperBroker(settings)
    try:print(json.dumps(run_reconcile(store,settings,broker),indent=2,default=str))
    finally:broker.close();store.close()


if __name__=='__main__':main()
