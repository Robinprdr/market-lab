"""Isolated one-share paper LOO connectivity trial; never creates a strategy signal."""
import argparse
from dataclasses import replace
import json

from .broker_ibkr import IBKRPaperBroker
from .calendar import before_next_open,last_complete_session,next_session
from .config import from_env
from .models import Signal
from .portfolio import entry_intent
from .runtime import _submit,synchronize
from .storage import Store


def require_usd_cash(snapshot):
    if snapshot.available_cash<=0 or snapshot.verified_cash_by_currency.get('USD',0.)<=0:
        raise ValueError('Paper trial blocked: no verified USD buying cash; no implicit FX or margin')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker',required=True)
    parser.add_argument('--reference-close',required=True,type=float,
                        help='Verified unadjusted prior-session close in USD')
    parser.add_argument('--send',action='store_true',help='Actually submit one Paper LOO')
    args=parser.parse_args()
    settings=from_env()
    if settings.trading_mode!='PAPER' or not settings.trading_enabled:
        raise ValueError('PAPER and TRADING_ENABLED=true are required')
    if args.reference_close<=0 or not args.ticker.isalpha():
        raise ValueError('Use a positive USD close and one US stock symbol')
    day=last_complete_session()
    if not before_next_open(day):
        raise ValueError('Next opening auction is no longer available')
    entry=next_session(day)
    broker=IBKRPaperBroker(settings)
    store=Store(settings.db_path)
    try:
        snapshot=synchronize(store,broker,settings.allowed_account_id)
        require_usd_cash(snapshot)
        signal=Signal('PAPER_CONNECTIVITY_TEST',args.ticker.upper(),day,entry,entry,
                      args.reference_close,'isolated IBKR Paper connectivity trial',1)
        candidate,reason=entry_intent(signal,store,snapshot,settings)
        if reason:
            raise ValueError('Paper trial risk check: '+reason)
        intent=replace(candidate,quantity=1)
        result=dict(account_id=intent.account_id,ticker=intent.ticker,quantity=1,
                    order_type=intent.order_type,limit_price=intent.limit_price,
                    intended_entry_date=intent.intended_entry_date,exit_date=intent.target_exit_date,
                    status='PREVIEW')
        if args.send:
            store.register(signal.strategy_id,'bot/paper_order_test.py')
            store.save_signal(signal)
            previous=store.save_intent(intent,'PLANNED')
            if previous['status']!='PLANNED':
                raise ValueError('Paper trial intent already used; no duplicate submission')
            result['broker_order_id']=_submit(store,broker,intent,settings)
            result['status']='ACKNOWLEDGED'
            synchronize(store,broker,settings.allowed_account_id)
        print(json.dumps(result,sort_keys=True))
    finally:
        broker.close();store.close()


if __name__=='__main__':
    main()
