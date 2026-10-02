"""After-close daily signal and next-open paper order pipeline."""
import argparse
import json
from .broker_ibkr import IBKRPaperBroker
from .config import from_env
from .market_data import YahooDailyProvider
from .runtime import run_daily
from .storage import Store
from .strategy import FrozenSwingV2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--asof',help='Completed YYYY-MM-DD session, DRY_RUN only')
    args=parser.parse_args()
    settings=from_env()
    if args.asof and settings.trading_mode!='DRY_RUN':
        parser.error('--asof is only available in DRY_RUN')
    store=Store(settings.db_path)
    broker=IBKRPaperBroker(settings) if settings.trading_mode=='PAPER' and settings.trading_enabled else None
    try:
        result=run_daily(store,settings,FrozenSwingV2(),YahooDailyProvider(),broker,args.asof)
        print(json.dumps(result,indent=2,default=str))
    finally:
        if broker:broker.close()
        store.close()


if __name__=='__main__':main()
