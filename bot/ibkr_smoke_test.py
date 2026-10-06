"""Read-only, account-scoped IB Gateway Paper smoke test. No order submission."""
import json
import sys

from .broker_ibkr import IBKRPaperBroker
from .config import from_env


def smoke(settings, broker_factory=IBKRPaperBroker):
    settings.validate()
    if settings.trading_mode != 'PAPER' or not settings.allowed_account_id.startswith('DU'):
        raise ValueError('An explicit paper account is required')
    broker = broker_factory(settings)
    try:
        broker.connect()
        first_id = broker.app.next_id
        if first_id is None or first_id < 0:
            raise RuntimeError('Missing nextValidId')
        if settings.allowed_account_id not in broker.app.accounts:
            raise RuntimeError('Allowed paper account absent')
        first = broker.snapshot(settings.allowed_account_id)
        if first.account_id != settings.allowed_account_id or first.total_cash is None or first.net_liquidation is None:
            raise RuntimeError('Incomplete account-scoped snapshot')
        broker.close()
        broker.connect()
        second = broker.snapshot(settings.allowed_account_id)
        if second.account_id != settings.allowed_account_id or broker.app.next_id is None:
            raise RuntimeError('Reconnect failed')
        return dict(status='PASS', account_id=second.account_id, first_order_id=first_id,
                    reconnected_order_id=broker.app.next_id, cash=second.total_cash,
                    available_cash=second.available_cash, net_liquidation=second.net_liquidation,
                    account_currency=second.account_currency,
                    cash_by_currency=second.cash_by_currency,
                    available_cash_by_currency=second.available_cash_by_currency,
                    settled_cash_by_currency=second.settled_cash_by_currency,
                    verified_cash_by_currency=second.verified_cash_by_currency,
                    account_values=second.account_values,
                    cash_verdict='USD_CASH_CONFIRMED' if second.cash_by_currency.get('USD',0)>0 else 'USD_CASH_NOT_VISIBLE',
                    positions={key:value.quantity for key,value in second.positions.items()},
                    open_orders=len(second.open_orders), executions_seen=len(second.executions),
                    account_summary_accessible=True, reconnect=True)
    finally:
        broker.close()


def main():
    try:
        print(json.dumps(smoke(from_env()), sort_keys=True))
    except Exception as exc:
        print(json.dumps(dict(status='FAIL', error=str(exc)), sort_keys=True), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
