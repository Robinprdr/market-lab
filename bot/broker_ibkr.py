"""Official TWS/IB Gateway socket adapter. Only the allowlisted paper account.

IB's official `ibapi` must be installed from its TWS API package. Import is
lazy so offline dry runs and tests never require the package or a connection.
"""
import threading

from .models import BrokerExecution,BrokerOrder,BrokerPosition,BrokerSnapshot
from .account_cash import currency_cash,numeric
from .execution_time import execution_timestamp


class IBKRPaperBroker:
    def __init__(self,settings,timeout=15):
        settings.validate()
        if settings.trading_mode!='PAPER':
            raise ValueError('IBKR adapter accepts PAPER only')
        if not settings.allowed_account_id.startswith('DU'):
            raise ValueError('An explicit DU paper account is required for IBKR access')
        self.settings=settings;self.timeout=timeout;self.app=None;self.thread=None
        self.order_lock=threading.Lock()

    def connect(self):
        if self.app is not None and self.app.isConnected():
            return
        try:
            from ibapi.client import EClient
            from ibapi.wrapper import EWrapper
        except ImportError as exc:
            raise RuntimeError('Install official IBKR TWS API Python package (ibapi) before PAPER mode') from exc
        allowed=self.settings.allowed_account_id

        class App(EWrapper,EClient):
            def __init__(self):
                EWrapper.__init__(self);EClient.__init__(self,self)
                self.ready=threading.Event();self.accounts_ready=threading.Event()
                self.account_done=threading.Event();self.orders_done=threading.Event()
                self.executions_done=threading.Event();self.ack_events={};self.ack_status={}
                self.accounts=[];self.next_id=None;self.cash_values={}
                self.positions={};self.open_orders=[];self.executions=[];self.errors=[];self.contracts={};self.contract_events={}

            def nextValidId(self,orderId):
                self.next_id=int(orderId);self.ready.set()

            def managedAccounts(self,accountsList):
                self.accounts=[x.strip() for x in accountsList.split(',') if x.strip()];self.accounts_ready.set()

            def updateAccountValue(self,key,val,currency,accountName):
                tag=key[len('$LEDGER-'):] if key.startswith('$LEDGER-') else key
                if accountName==allowed and tag in (
                        'AvailableFunds','TotalCashValue','CashBalance','TotalCashBalance',
                        'SettledCash','SettledCashByDate','BuyingPower','NetLiquidation','Currency',
                        'NetLiquidationByCurrency'):
                    self.cash_values[(key,currency)]=str(val)

            def updatePortfolio(self,contract,position,marketPrice,marketValue,averageCost,unrealizedPNL,realizedPNL,accountName):
                if accountName!=allowed or contract.secType!='STK':return
                ticker='BRK-B' if contract.symbol in ('BRK B','BRK.B') else contract.symbol
                if float(position)!=int(position):
                    self.errors.append('Fractional position cannot be reconciled safely');return
                # marketValue is in account base currency; price is in contract currency.
                if int(position) and contract.currency!='USD':
                    self.errors.append('Non-USD stock exposure unsupported');return
                if int(position) and (numeric(marketPrice) is None or float(marketPrice)<=0):
                    self.errors.append('Unverified USD stock price');return
                if int(position):self.positions[ticker]=BrokerPosition(ticker,int(position),float(marketPrice)*int(position))
                else:self.positions.pop(ticker,None)

            def accountDownloadEnd(self,accountName):
                if accountName==allowed:self.account_done.set()

            def openOrder(self,orderId,contract,order,orderState):
                if order.account!=allowed:return
                ticker='BRK-B' if contract.symbol in ('BRK B','BRK.B') else contract.symbol
                self.open_orders.append(BrokerOrder(int(orderId),str(order.orderRef),ticker,str(order.action),
                    int(order.totalQuantity),str(orderState.status),order.account))
                self.ack_status[int(orderId)]=str(orderState.status)
                event=self.ack_events.get(int(orderId))
                if event:event.set()

            def openOrderEnd(self):self.orders_done.set()

            def orderStatus(self,orderId,status,filled,remaining,avgFillPrice,permId,parentId,lastFillPrice,clientId,whyHeld,mktCapPrice):
                self.ack_status[int(orderId)]=str(status)
                event=self.ack_events.get(int(orderId))
                if event:event.set()

            def execDetails(self,reqId,contract,execution):
                if execution.acctNumber!=allowed:return
                ticker='BRK-B' if contract.symbol in ('BRK B','BRK.B') else contract.symbol
                try:
                    session=execution_timestamp(execution.time).date().isoformat()
                except ValueError as exc:
                    self.errors.append(str(exc));return
                side={'BOT':'BUY','SLD':'SELL','BUY':'BUY','SELL':'SELL'}.get(str(execution.side).upper())
                if side is None:
                    self.errors.append('Unknown execution side');return
                self.executions.append(BrokerExecution(str(execution.execId),int(execution.orderId),ticker,side,
                    int(execution.shares),float(execution.price),session,execution.acctNumber))

            def execDetailsEnd(self,reqId):
                if reqId==9001:self.executions_done.set()

            def contractDetails(self,reqId,contractDetails):
                self.contracts.setdefault(reqId,[]).append(contractDetails.contract)

            def contractDetailsEnd(self,reqId):
                event=self.contract_events.get(reqId)
                if event:event.set()

            def error(self,reqId,errorCode,errorString,*args):
                # API 10.51 adds errorTime before errorCode; older releases do not.
                if isinstance(errorString,int) and args:
                    errorCode,errorString=errorString,args[0]
                if int(errorCode) not in (2100,2104,2106,2107,2108,2158):
                    self.errors.append(f'{reqId}:{errorCode}:{errorString}')
                    event=self.ack_events.get(int(reqId)) if isinstance(reqId,int) else None
                    if event:event.set()
                    contract_event=self.contract_events.get(int(reqId)) if isinstance(reqId,int) else None
                    if contract_event:contract_event.set()

        app=App()
        try:
            app.connect(self.settings.ibkr_host,self.settings.ibkr_port,self.settings.ibkr_client_id)
        except (ConnectionError,OSError) as exc:
            raise RuntimeError('IBKR socket connection failed') from exc
        if not app.isConnected():
            raise RuntimeError('IBKR socket connection failed')
        self.thread=threading.Thread(target=app.run,daemon=True)
        self.thread.start();self.app=app
        if not app.ready.wait(self.timeout) or not app.accounts_ready.wait(self.timeout):
            self.close();raise RuntimeError('IBKR handshake timeout')
        if allowed not in app.accounts:
            self.close();raise RuntimeError('Configured paper account is not accessible; refusing all orders')

    def _wait(self,event,label):
        if not event.wait(self.timeout):
            raise RuntimeError('IBKR timeout: '+label)

    def snapshot(self,account_id):
        if account_id!=self.settings.allowed_account_id:
            raise ValueError('Account allowlist mismatch')
        self.connect();app=self.app
        app.account_done.clear();app.orders_done.clear();app.executions_done.clear()
        app.positions={};app.open_orders=[];app.executions=[];app.cash_values={};app.errors=[]
        app.reqAccountUpdates(True,account_id)
        try:
            self._wait(app.account_done,'account download')
        finally:
            app.reqAccountUpdates(False,account_id)
        app.reqOpenOrders();self._wait(app.orders_done,'open orders')
        from ibapi.execution import ExecutionFilter
        filt=ExecutionFilter();filt.acctCode=account_id
        app.reqExecutions(9001,filt);self._wait(app.executions_done,'executions')
        currencies={currency for key,currency in app.cash_values if key=='NetLiquidation'}
        if len(currencies)!=1:
            raise RuntimeError('IBKR account base currency is ambiguous')
        currency=currencies.pop()
        cash=numeric(app.cash_values.get(('TotalCashValue',currency)))
        available=numeric(app.cash_values.get(('AvailableFunds',currency)))
        net_liquidation=numeric(app.cash_values.get(('NetLiquidation',currency)))
        if app.errors or cash is None or available is None or net_liquidation is None or not app.isConnected():
            raise RuntimeError('IBKR snapshot incomplete: '+','.join(app.errors[:3]))
        balances,funds,settled,verified=currency_cash(app.cash_values)
        # Base funds can block, never fund, a USD order. BuyingPower is diagnostic only.
        usd_available=verified.get('USD',0.) if available>0 else 0.
        raw={}
        for (key,cur),value in app.cash_values.items():raw.setdefault(key,{})[cur]=value
        return BrokerSnapshot(account_id,usd_available,dict(app.positions),tuple(app.open_orders),
                              tuple(app.executions),cash,net_liquidation,currency,
                              balances,funds,settled,verified,raw)

    def _contract(self,ticker):
        from ibapi.contract import Contract
        self.connect();app=self.app
        contract=Contract();contract.symbol='BRK B' if ticker=='BRK-B' else ticker
        contract.secType='STK';contract.exchange='SMART';contract.currency='USD'
        with self.order_lock:
            req=app.next_id;app.next_id+=1
        event=threading.Event();app.contract_events[req]=event;app.contracts[req]=[]
        app.reqContractDetails(req,contract);self._wait(event,'contract qualification')
        choices=[c for c in app.contracts.pop(req) if c.secType=='STK' and c.currency=='USD']
        app.contract_events.pop(req,None)
        ids={c.conId for c in choices}
        if len(ids)!=1:
            raise RuntimeError(f'{ticker}: ambiguous/unavailable IBKR contract')
        return choices[0]

    def submit(self,intent):
        if intent.account_id!=self.settings.allowed_account_id or self.settings.trading_mode!='PAPER' or not self.settings.trading_enabled:
            raise ValueError('Paper account, mode, or kill-switch check failed')
        if intent.quantity<=0 or intent.side not in ('BUY','SELL') or intent.order_type not in ('LOO','MOC'):
            raise ValueError('Invalid order intent')
        if (intent.side,intent.order_type) not in (('BUY','LOO'),('SELL','MOC')):
            raise ValueError('Only paper long entry/exit orders are supported')
        self.connect();contract=self._contract(intent.ticker)
        from ibapi.order import Order
        order=Order();order.account=intent.account_id;order.action=intent.side
        order.totalQuantity=intent.quantity;order.orderRef=intent.intent_id
        order.outsideRth=False;order.transmit=True
        if intent.order_type=='LOO':
            if intent.limit_price is None or intent.limit_price<=0:
                raise ValueError('Missing LOO cap')
            order.orderType='LMT';order.tif='OPG';order.lmtPrice=intent.limit_price
        else:
            order.orderType='MOC';order.tif='DAY'
        with self.order_lock:
            order_id=self.app.next_id;self.app.next_id+=1
        event=threading.Event();self.app.ack_events[order_id]=event
        try:
            self.app.placeOrder(order_id,contract,order)
            self._wait(event,'order acknowledgement')
            if self.app.ack_status.get(order_id) in ('Inactive','Cancelled','ApiCancelled'):
                raise RuntimeError('IBKR order is inactive/cancelled; inspect local IBKR logs')
            if any(str(e).startswith(str(order_id)+':') for e in self.app.errors):
                raise RuntimeError('IBKR rejected order; inspect local IBKR logs')
            if not self.app.isConnected():
                raise RuntimeError('IBKR disconnected during submission')
            return order_id
        finally:
            self.app.ack_events.pop(order_id,None)

    def close(self):
        if self.app is not None:
            self.app.disconnect();self.app=None
        if self.thread is not None:
            self.thread.join(timeout=2);self.thread=None
