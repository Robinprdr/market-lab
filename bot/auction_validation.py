"""Manual, isolated one-share Paper OPG/MOC validation. No strategy changes."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time

import pandas as pd

from .broker_ibkr import IBKRPaperBroker
from .calendar import before_moc_cutoff, exchange, last_complete_session
from .config import Settings
from .models import OrderIntent, Signal
from .portfolio import entry_intent, intent_id
from .runtime import _submit, synchronize
from .storage import Store, now

ACCOUNT = 'DUR231204'
TICKER = 'AAPL'
STRATEGY = 'PAPER_TEST_OPG'
ROOT = Path(__file__).resolve().parents[1]


def schedule(day):
    row = exchange(day).schedule.loc[pd.Timestamp(day)]
    return row['open'], row['close']


def safe_limit(reference, ceiling=None):
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError('Invalid verified reference close')
    # Test-only 0.5% cap, not a change to Swing V2 or a trading rule.
    calculated = reference * 1.005
    if ceiling is not None:
        if not math.isfinite(ceiling) or ceiling <= 0:
            raise ValueError('Invalid current broker ceiling')
        calculated = min(calculated, ceiling * .999)
    return math.floor(calculated * 100) / 100


def order_for(intent):
    from ibapi.order import Order
    if (intent.account_id != ACCOUNT or intent.strategy_id != STRATEGY
            or intent.ticker != TICKER or intent.quantity != 1):
        raise ValueError('Exact isolated Paper test scope required')
    if (intent.side, intent.order_type) not in (('BUY', 'LOO'), ('SELL', 'MOC')):
        raise ValueError('Only OPG entry and MOC exit allowed')
    order = Order()
    order.account = ACCOUNT
    order.action = intent.side
    order.totalQuantity = 1
    order.orderRef = intent.intent_id
    order.outsideRth = False
    order.transmit = True
    order.eTradeOnly = False
    order.firmQuoteOnly = False
    order.orderType = 'LMT' if intent.side == 'BUY' else 'MOC'
    order.tif = 'OPG' if intent.side == 'BUY' else 'DAY'
    if intent.side == 'BUY':
        if intent.limit_price is None or not 0 < intent.limit_price <= 1000:
            raise ValueError('Missing/unsafe entry cap')
        order.lmtPrice = intent.limit_price
    return order


class Audit:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.failed = False

    def emit(self, event, **fields):
        # Timestamp may already be provided by a callback: never duplicate kwargs.
        record = {'event': event, 'at_utc': now(), **fields}
        try:
            line = json.dumps(record, allow_nan=False)
            with self.lock:
                with self.path.open('a') as output:
                    output.write(line + '\n')
                print(line, flush=True)
        except Exception:
            self.failed = True  # Never kill the IBKR receive thread with a log failure.


class AuctionBroker(IBKRPaperBroker):
    def __init__(self, settings, audit, day):
        super().__init__(settings)
        self.audit, self.day = audit, day
        self.fill_times = {}
        self.stop_path = ROOT / 'data/cache/bot_core' / ('auction_' + day + '.stop')

    def connect(self):
        already = self.app is not None and self.app.isConnected()
        super().connect()
        if already:
            return
        original = self.app.orderStatus
        def status(*args):
            original(*args)
            self.audit.emit('ORDER_STATUS', order_id=args[0], status=args[1],
                            filled=float(args[2]), remaining=float(args[3]),
                            avg_fill_price=args[4], perm_id=args[5])
        self.app.orderStatus = status
        def fees(report):
            self.audit.emit('COMMISSION', execution_id=report.execId,
                            commission=report.commissionAndFees, currency=report.currency)
        self.app.commissionAndFeesReport = fees
        original_execution = self.app.execDetails
        def execution(req, contract, fill):
            original_execution(req, contract, fill)
            if fill.acctNumber == ACCOUNT:
                self.fill_times[int(fill.orderId)] = str(fill.time)
                self.audit.emit('EXECUTION', execution_id=fill.execId, order_id=fill.orderId,
                                perm_id=fill.permId, exchange_time=fill.time,
                                ticker=contract.symbol, side=fill.side, quantity=float(fill.shares), price=fill.price)
        self.app.execDetails = execution
        original_error = self.app.error
        def error(*args):
            original_error(*args)
            self.audit.emit('IBKR_ERROR', details=list(args))
        self.app.error = error
        # Include orders from other API clients in account-scoped preflight.
        self.app.reqOpenOrders = self.app.reqAllOpenOrders

    def reference(self):
        contract = self._contract(TICKER)
        done, bars = threading.Event(), []
        self.app.historicalData = lambda rid, bar: bars.append(bar) if rid == 9203 else None
        self.app.historicalDataEnd = lambda rid, *args: done.set() if rid == 9203 else None
        self.app.reqHistoricalData(9203, contract, '', '5 D', '1 day', 'TRADES', 1, 1, False, [])
        if not done.wait(20):
            raise RuntimeError('Reference price timeout')
        cal = exchange(self.day)
        previous_day = cal.previous_session(pd.Timestamp(self.day)).date().isoformat()
        # A preview before today's close must not call a partial daily bar a completed close.
        previous_day = min(previous_day, last_complete_session())
        previous = previous_day.replace('-', '')
        self.reference_session = previous_day
        found = [bar for bar in bars if str(bar.date) == previous]
        if len(found) != 1:
            raise RuntimeError('Prior-session unadjusted close unavailable')
        return float(found[0].close)

    def submit(self, intent):
        if (self.settings.trading_mode != 'PAPER' or not self.settings.trading_enabled
                or self.settings.allowed_account_id != ACCOUNT or self.audit.failed or self.stop_path.exists()):
            raise ValueError('Paper/account/kill-switch/audit guard failed')
        utc = pd.Timestamp.now(tz='UTC')
        opening, closing = schedule(self.day)
        if intent.side == 'BUY' and not opening - pd.Timedelta(minutes=30) <= utc < opening:
            raise ValueError('OPG requires same-session pre-open window')
        if intent.side == 'SELL' and not before_moc_cutoff(self.day, utc):
            raise ValueError('Conservative MOC deadline closed')
        snapshot = self.snapshot(ACCOUNT)
        # A durable SUBMITTING claim already exists; do not treat our own claim as an uncertain prior submission.
        for execution in snapshot.executions:
            store.sync_execution(execution)
        local = {t: p['quantity'] for t, p in store.positions(ACCOUNT).items()}
        if local != {t: p.quantity for t, p in snapshot.positions.items()}:
            raise ValueError('Pre-submit position reconciliation mismatch')
        # _submit already claimed this intent; no other active intents allowed.
        others = [r for r in store.active_intents() if r['intent_id'] != intent.intent_id]
        if snapshot.open_orders or others:
            raise ValueError('Unexpected/pending order')
        if intent.side == 'BUY':
            verified_cash = min(snapshot.settled_cash_by_currency.get('USD', 0),
                                snapshot.verified_cash_by_currency.get('USD', 0), snapshot.available_cash)
            if snapshot.positions or not math.isfinite(verified_cash) or verified_cash < intent.limit_price + 5:
                raise ValueError('Unexpected position/insufficient USD settled cash')
        else:
            position = store.position(ACCOUNT, TICKER)
            if (set(snapshot.positions) != {TICKER} or snapshot.positions[TICKER].quantity != 1
                    or position is None or position['strategy_id'] != STRATEGY):
                raise ValueError('Exit is not the verified one-share OPG test position')
        order = order_for(intent)
        contract = self._contract(TICKER)
        with self.order_lock:
            oid = self.app.next_id
            self.app.next_id += 1
        event = threading.Event()
        self.app.ack_events[oid] = event
        self.audit.emit('SUBMITTED', order_id=oid, side=intent.side, quantity=1,
                        order_type=order.orderType, tif=order.tif, account=ACCOUNT,
                        order_ref=intent.intent_id, limit_price=intent.limit_price)
        if self.audit.failed:
            raise RuntimeError('Audit failed before submission; no order sent')
        self.app.placeOrder(oid, contract, order)
        self._wait(event, 'auction acknowledgement')
        status = self.app.ack_status.get(oid)
        if status in ('Inactive', 'Cancelled', 'ApiCancelled') or any(
                e.startswith(str(oid) + ':') for e in self.app.errors):
            raise RuntimeError('Auction rejected/cancelled; inspect audit')
        self.audit.emit('ACKNOWLEDGED', order_id=oid, status=status)
        return oid


def verify_auction_time(broker, oid, auction, start, end):
    text = broker.fill_times.get(oid, '')
    parts = text.split()
    if len(parts) != 3 or parts[2] not in ('US/Eastern', 'America/New_York'):
        raise RuntimeError('Execution timezone unavailable/unrecognized: ' + text)
    timestamp = pd.Timestamp(datetime.strptime(' '.join(parts[:2]), '%Y%m%d %H:%M:%S')).tz_localize('America/New_York').tz_convert('UTC')
    if not start <= timestamp <= end:
        raise RuntimeError(auction + ' execution outside expected auction time: ' + text)
    broker.audit.emit('AUCTION_TIME_CONFIRMED', auction=auction, order_id=oid, execution_time=text)


def wait_fill(broker, oid, deadline):
    while pd.Timestamp.now(tz='UTC') < deadline:
        if not broker.app.isConnected() or not broker.thread.is_alive() or broker.audit.failed or broker.stop_path.exists():
            raise RuntimeError('Connection/receiver/audit lost; uncertain order, no resubmission')
        status = broker.app.ack_status.get(oid)
        if status == 'Filled':
            return
        if status in ('Inactive', 'Cancelled', 'ApiCancelled'):
            raise RuntimeError('Order ended ' + str(status))
        time.sleep(1)
    raise RuntimeError('Auction fill not confirmed by deadline; STOP, no substitute/resubmission')


def reconcile(broker, ledger):
    for attempt in range(3):
        try:
            return synchronize(ledger, broker, ACCOUNT)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def main():
    global store  # Scoped to this one locked manual test process, never strategy runtime.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, help='NYSE session YYYY-MM-DD')
    parser.add_argument('--send', action='store_true', help='One OPG entry, then one MOC exit; blocks until close')
    args = parser.parse_args()
    opening, closing = schedule(args.session)
    utc = pd.Timestamp.now(tz='UTC')
    if args.send and not opening - pd.Timedelta(minutes=30) <= utc < opening:
        raise ValueError('Launch --send between 09:00 and 09:30 ET on the specified session')
    settings = Settings(allowed_account_id=ACCOUNT, ibkr_port=4002, ibkr_client_id=82,
                        trading_enabled=args.send).validate()
    audit = Audit(ROOT / 'data/cache/bot_core' / ('auction_' + args.session + '.jsonl'))
    broker = AuctionBroker(settings, audit, args.session)
    store = Store(settings.db_path)
    run = store.run_start('auction_validation', 'PAPER', args.session)
    try:
        snapshot = synchronize(store, broker, ACCOUNT)
        if snapshot.positions or snapshot.open_orders or store.active_intents():
            raise ValueError('Account/ledger must be flat with no pending intents')
        reference = broker.reference()
        signal = Signal(STRATEGY, TICKER, args.session, args.session, args.session,
                        reference, 'Isolated user-authorized OPG/MOC test; no strategy signal', 1)
        candidate, reason = entry_intent(signal, store, snapshot, settings)
        if reason or snapshot.settled_cash_by_currency.get('USD', 0) <= 0:
            raise ValueError('Preflight failed: ' + str(reason))
        buy = replace(candidate, intent_id='PAPER_TEST_OPG_' + candidate.intent_id, quantity=1,
                      limit_price=min(candidate.limit_price, safe_limit(reference)))
        audit.emit('PREFLIGHT_PASS', account=ACCOUNT, settled_usd=snapshot.settled_cash_by_currency['USD'],
                   ticker=TICKER, quantity=1, reference_close=reference, reference_session=broker.reference_session, calculated_limit=buy.limit_price,
                   current_ibkr_ceiling=None, ceiling_note='No authoritative pre-submit ceiling exposed; prior rejected ceiling is not reused',
                   opening_et=opening.tz_convert('America/New_York').isoformat(),
                   closing_et=closing.tz_convert('America/New_York').isoformat(),
                   conservative_moc_deadline_et=(closing-pd.Timedelta(hours=1)).tz_convert('America/New_York').isoformat())
        if not args.send:
            store.run_end(run, 'PREVIEW'); return
        if store.intent(buy.intent_id):
            raise ValueError('Test already attempted this session: no duplicate entry')
        store.register(STRATEGY, 'bot/auction_validation.py')
        store.save_intent(buy, 'PLANNED')
        bid = _submit(store, broker, buy, settings)
        wait_fill(broker, bid, opening + pd.Timedelta(minutes=5))
        snapshot = reconcile(broker, store)
        if set(snapshot.positions) != {TICKER} or snapshot.positions[TICKER].quantity != 1:
            raise RuntimeError('OPG position mismatch')
        verify_auction_time(broker, bid, 'OPG', opening, opening + pd.Timedelta(minutes=5))
        audit.emit('OPG_PASS', order_id=bid, sqlite_quantity=1, ibkr_quantity=1, reconciliation='PASS')
        sell = OrderIntent('PAPER_TEST_OPG_' + intent_id(STRATEGY,TICKER,'SELL',args.session,ACCOUNT,'PAPER'),
                           STRATEGY,TICKER,'SELL',1,args.session,'PAPER_TEST MOC close',now(),1,
                           args.session,'MOC',None,ACCOUNT,reference)
        store.save_intent(sell,'PLANNED')
        sid = _submit(store,broker,sell,settings)
        wait_fill(broker,sid,closing+pd.Timedelta(minutes=10))
        snapshot = reconcile(broker,store)
        if snapshot.positions or snapshot.open_orders or store.positions(ACCOUNT) or store.active_intents():
            raise RuntimeError('Final state not flat')
        verify_auction_time(broker, sid, 'MOC', closing, closing + pd.Timedelta(minutes=10))
        result = dict(opg='PASS',moc='PASS',entry_order_id=bid,exit_order_id=sid,
                      positions=0,open_orders=0,reconciliation='PASS')
        audit.emit('FINAL_PASS',**result)
        store.run_end(run,'OK',result)
    except Exception as exc:
        audit.emit('STOP',error=str(exc))
        if broker.app is not None and broker.app.isConnected():
            done = threading.Event()
            def completed(contract, order, state):
                if order.account == ACCOUNT and order.orderRef.startswith('PAPER_TEST_OPG_'):
                    audit.emit('COMPLETED_ORDER', order_id=order.orderId, perm_id=order.permId,
                               status=state.status, completed_time=state.completedTime, reason=state.completedStatus)
            broker.app.completedOrder = completed
            broker.app.completedOrdersEnd = lambda: done.set()
            broker.app.reqCompletedOrders(False)
            done.wait(15)
        store.error(run,'AUCTION_VALIDATION_STOP',str(exc))
        store.run_end(run,'FAILED',dict(error=str(exc)))
        raise
    finally:
        broker.close();store.close()


if __name__ == '__main__':
    main()
