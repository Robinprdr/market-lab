"""Manual, isolated one-share Paper OPG/MOC validation. No strategy changes."""
from datetime import datetime
import json
import math
from pathlib import Path
import threading
import time

import pandas as pd

from .broker_ibkr import IBKRPaperBroker
from .calendar import exchange
from .storage import now

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
    """Short-lived API connection with durable order/execute evidence."""
    def __init__(self, settings, audit, day):
        super().__init__(settings)
        self.audit, self.day = audit, day
        self.fill_times = {}
        self.records, self.fill_metadata, self.fees = [], {}, {}
        self.capture_lock = threading.Lock()
        self.stop_path = ROOT / 'data/cache/bot_core' / ('auction_' + day + '.stop')

    def connect(self):
        already = self.app is not None and self.app.isConnected()
        super().connect()
        if already:
            return
        original_status, original_open, original_exec = self.app.orderStatus, self.app.openOrder, self.app.execDetails
        def status(*args):
            original_status(*args)
            self.audit.emit('ORDER_STATUS',order_id=args[0],status=args[1],filled=float(args[2]),
                            remaining=float(args[3]),avg_fill_price=args[4],perm_id=args[5])
        def capture(contract, order, state, oid, kind):
            if order.account != ACCOUNT:
                return
            record = dict(ref=str(order.orderRef),oid=int(oid),perm_id=int(order.permId),
                          account=order.account,ticker=contract.symbol,currency=contract.currency,
                          security_type=contract.secType,side=order.action,quantity=float(order.totalQuantity),
                          order_type=order.orderType,tif=order.tif,limit_price=float(order.lmtPrice) if order.orderType=='LMT' else None,
                          status=state.status,reason=getattr(state,'completedStatus',''),kind=kind)
            with self.capture_lock:
                self.records.append(record)
            self.audit.emit('BROKER_ORDER',**record)
        def opened(oid, contract, order, state):
            original_open(oid,contract,order,state)
            capture(contract,order,state,oid,'open')
        def completed(contract,order,state):
            capture(contract,order,state,order.orderId,'completed')
        def execution(req,contract,fill):
            original_exec(req,contract,fill)
            if fill.acctNumber != ACCOUNT:
                return
            meta=dict(execution_id=fill.execId,oid=int(fill.orderId),perm_id=int(fill.permId),
                      exchange_time=str(fill.time),account=fill.acctNumber,currency=contract.currency,
                      security_type=contract.secType,ticker=contract.symbol)
            with self.capture_lock:
                self.fill_metadata[str(fill.execId)] = meta
                self.fill_times[int(fill.orderId)] = str(fill.time)
            self.audit.emit('EXECUTION',**meta,price=float(fill.price),quantity=float(fill.shares),side=fill.side)
        def fees(report):
            with self.capture_lock:
                self.fees[str(report.execId)] = dict(commission=float(report.commissionAndFees),currency=report.currency)
        self.app.orderStatus=status;self.app.openOrder=opened;self.app.completedOrder=completed
        self.app.execDetails=execution;self.app.commissionAndFeesReport=fees
        self.app.reqOpenOrders=self.app.reqAllOpenOrders

    def evidence(self):
        self.connect()
        with self.capture_lock:
            self.records=[]
        snapshot=self.snapshot(ACCOUNT)
        done=threading.Event()
        self.app.completedOrdersEnd=lambda:done.set()
        self.app.reqCompletedOrders(False)
        self._wait(done,'completed orders')
        if not self.thread.is_alive() or not self.app.isConnected() or self.audit.failed:
            raise RuntimeError('Connection/receiver/audit unavailable')
        with self.capture_lock:
            return snapshot,list(self.records),dict(self.fill_metadata),dict(self.fees)

    def reference(self):
        contract=self._contract(TICKER)
        done,bars=threading.Event(),[]
        self.app.historicalData=lambda rid,bar:bars.append(bar) if rid==9203 else None
        self.app.historicalDataEnd=lambda rid,*a:done.set() if rid==9203 else None
        self.app.reqHistoricalData(9203,contract,'','5 D','1 day','TRADES',1,1,False,[])
        self._wait(done,'reference close')
        previous=exchange(self.day).previous_session(pd.Timestamp(self.day)).date().strftime('%Y%m%d')
        found=[b for b in bars if str(b.date)==previous]
        if len(found)!=1:
            raise RuntimeError('Prior-session unadjusted close unavailable')
        return float(found[0].close)

    def reserve(self, intent):
        self.contract=self._contract(intent.ticker)
        with self.order_lock:
            oid=self.app.next_id;self.app.next_id+=1
        return oid

    def send(self,intent,oid):
        order=order_for(intent)
        if (self.settings.trading_mode!='PAPER' or not self.settings.trading_enabled
                or self.settings.allowed_account_id!=ACCOUNT or self.audit.failed or self.stop_path.exists()):
            raise ValueError('Paper/account/kill-switch/audit guard failed')
        from .auction_checkpoints import phase_window, guard_snapshot
        phase_window('enter' if intent.side=='BUY' else 'arm-exit',self.day,pd.Timestamp.now(tz='UTC'))
        guard_snapshot(self.snapshot(ACCOUNT),intent.side,intent.limit_price,self.settings.cash_buffer_usd)
        event=threading.Event();self.app.ack_events[oid]=event
        self.audit.emit('SUBMITTED',order_id=oid,order_ref=intent.intent_id,side=intent.side,
                        order_type=order.orderType,tif=order.tif,transmit=True,quantity=1)
        if self.audit.failed:
            raise RuntimeError('Audit failed before network submission')
        self.app.placeOrder(oid,self.contract,order)
        self._wait(event,'order acknowledgement')
        errors=[e for e in self.app.errors if e.startswith(str(oid)+':')]
        if errors or self.app.ack_status.get(oid) in ('Inactive','Cancelled','ApiCancelled'):
            raise RuntimeError('Broker refused order: '+str(errors))


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


def main():
    from .auction_checkpoints import main as checkpoint_main
    return checkpoint_main()


if __name__ == '__main__':
    raise SystemExit(main())
