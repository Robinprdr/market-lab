"""Durable, idempotent auction checkpoints. Broker evidence precedes every action."""
import argparse
from dataclasses import replace
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from .auction_validation import ACCOUNT, TICKER, STRATEGY, AuctionBroker, Audit, schedule, safe_limit, verify_auction_time
from .config import Settings
from .models import OrderIntent, Signal
from .portfolio import entry_intent, intent_id
from .storage import Store, now

TERMINAL={'Cancelled':'CANCELLED','ApiCancelled':'CANCELLED','Inactive':'REJECTED'}
ACCEPTED={'PreSubmitted','Submitted','Filled'}


def phase_window(phase,day,at):
    opening,closing=schedule(day)
    at=pd.Timestamp(at)
    if at.tzinfo is None:raise ValueError('Timezone-aware timestamp required')
    at=at.tz_convert('UTC')
    if phase=='enter' and not opening-pd.Timedelta(minutes=30)<=at<opening-pd.Timedelta(minutes=5):
        raise ValueError('OPG submission requires 09:00 <= ET < 09:25 on the session')
    if phase=='arm-exit' and not opening<=at<=closing-pd.Timedelta(hours=1):
        raise ValueError('MOC submission outside conservative session deadline')
    if phase=='verify-close' and at<closing:
        raise ValueError('verify-close requires session close to have passed')


def guard_snapshot(s,side,limit=None,buffer=5):
    if s.account_id!=ACCOUNT:raise ValueError('Wrong account')
    if s.open_orders:raise ValueError('Unexpected working order')
    if side=='BUY':
        cash=min(s.available_cash,s.verified_cash_by_currency.get('USD',0),s.settled_cash_by_currency.get('USD',0))
        if s.positions or not math.isfinite(cash) or cash<(limit or 0)+buffer:
            raise ValueError('Account not flat or verified settled USD insufficient')
    elif set(s.positions)!={TICKER} or s.positions[TICKER].quantity!=1:
        raise ValueError('Exact +1 AAPL position not confirmed')


class Checkpoints:
    def __init__(self,store,broker,settings,day,at=None):
        settings.validate()
        if settings.trading_mode!='PAPER' or settings.allowed_account_id!=ACCOUNT:
            raise ValueError('PAPER and exact DUR231204 required')
        self.store,self.broker,self.settings,self.day=store,broker,settings,day
        self.at=at or pd.Timestamp.now(tz='UTC')
        schedule(day)
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS auction_sessions(session TEXT PRIMARY KEY,account TEXT NOT NULL,
          ticker TEXT NOT NULL,marker TEXT NOT NULL,state TEXT NOT NULL,last_reconciled_at TEXT,report_json TEXT);
        CREATE TABLE IF NOT EXISTS auction_order_proofs(intent_id TEXT PRIMARY KEY,session TEXT NOT NULL,
          side TEXT NOT NULL,broker_order_id INTEGER NOT NULL,perm_id INTEGER,
          acknowledged INTEGER NOT NULL DEFAULT 0,broker_status TEXT,broker_terms_json TEXT,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auction_execution_proofs(execution_id TEXT PRIMARY KEY,
          intent_id TEXT NOT NULL,metadata_json TEXT NOT NULL,fees_json TEXT,observed_at TEXT NOT NULL);
        ''')
        store.db.commit()

    def ref(self,side):
        return 'PAPER_TEST_OPG_'+intent_id(STRATEGY,TICKER,side,self.day,ACCOUNT,'PAPER')

    def state(self,state,report=None):
        with self.store.tx() as db:
            db.execute('INSERT OR IGNORE INTO auction_sessions VALUES(?,?,?,?,?,?,?)',
                       (self.day,ACCOUNT,TICKER,STRATEGY,state,None,None))
            current=db.execute('SELECT state FROM auction_sessions WHERE session=?',(self.day,)).fetchone()
            rank={'ENTRY_SUBMITTING':1,'ENTRY_ACCEPTED':2,'ENTRY_FILLED':3,'EXIT_SUBMITTING':4,'EXIT_ACCEPTED':5,'EXIT_FILLED':6,'CLOSED':7}
            if report is None and rank.get(current['state'],0)>rank.get(state,0):
                db.execute('UPDATE auction_sessions SET last_reconciled_at=? WHERE session=?',(now(),self.day))
                return
            db.execute('UPDATE auction_sessions SET state=?,last_reconciled_at=?,report_json=? WHERE session=?',
                       (state,now(),json.dumps(report) if report else None,self.day))

    def stop(self,reason):
        with self.store.tx() as db:
            db.execute('UPDATE auction_sessions SET state=?,report_json=? WHERE session=?',
                       ('UNCERTAIN',json.dumps(dict(error=reason)),self.day))
        raise RuntimeError(reason)

    def recover(self):
        s,records,metadata,fees=self.broker.evidence()
        if s.account_id!=ACCOUNT:self.stop('Wrong broker account')
        refs={self.ref('BUY'),self.ref('SELL')}
        if any(o.intent_id not in refs for o in s.open_orders):self.stop('Unexpected broker open order')
        proofs=self.store.db.execute('SELECT * FROM auction_order_proofs WHERE session=?',(self.day,)).fetchall()
        for proof in proofs:
            intent=self.store.intent(proof['intent_id'])
            if intent is None:self.stop('Proof without intent')
            if (proof['side'] not in ('BUY','SELL') or proof['intent_id']!=self.ref(proof['side'])
                    or (intent['account_id'],intent['ticker'],intent['strategy_id'],intent['quantity'],intent['intended_entry_date'],intent['target_exit_date'])
                    !=(ACCOUNT,TICKER,STRATEGY,1,self.day,self.day)):
                self.stop('Stored test scope corrupted')
            matching=[r for r in records if r['ref']==proof['intent_id']]
            # open + completed snapshots must not present conflicting versions of a test order.
            identities={(r['perm_id'],r['status']) for r in matching}
            if len(identities)>1:self.stop('Conflicting broker order evidence')
            if matching:
                r=matching[-1]
                expected=('LMT','OPG') if proof['side']=='BUY' else ('MOC','DAY')
                if (r['account'],r['ticker'],r['currency'],r['security_type'],r['side'],r['quantity'],r['order_type'],r['tif']) != (
                        ACCOUNT,TICKER,'USD','STK',proof['side'],1,*expected):self.stop('Broker order terms mismatch')
                if r['oid']>0 and r['oid']!=proof['broker_order_id']:self.stop('Broker order ID mismatch')
                if r['perm_id']<=0 or proof['perm_id'] not in (None,r['perm_id']):self.stop('permId mismatch/missing')
                if proof['side']=='BUY' and abs(r['limit_price']-intent['limit_price'])>.000001:self.stop('Broker limit changed')
                if r['status'] not in ACCEPTED and r['status'] not in TERMINAL:self.stop('Order status uncertain: '+r['status'])
                with self.store.tx() as db:
                    db.execute('UPDATE auction_order_proofs SET perm_id=?,acknowledged=1,broker_status=?,broker_terms_json=?,updated_at=? WHERE intent_id=?',
                               (r['perm_id'],r['status'],json.dumps(r),now(),proof['intent_id']))
                # Bind before execution import, including recovery after placeOrder/ack crash.
                if intent['status']!='FILLED':
                    self.store.order_ack(proof['intent_id'],proof['broker_order_id'],TERMINAL.get(r['status'],'ACKNOWLEDGED'))
            elif not proof['acknowledged']:
                self.stop('Submission uncertain/absent; never resubmit')
        # Replay buys before sells and use execution IDs to avoid duplicate position changes.
        for ex in sorted(s.executions,key=lambda e:(e.session,e.side!='BUY',e.execution_id)):
            row=self.store.db.execute('SELECT intent_id FROM orders WHERE broker_order_id=? AND account_id=?',
                                      (ex.broker_order_id,ACCOUNT)).fetchone()
            if row and row['intent_id'] in refs:
                p=self.store.db.execute('SELECT * FROM auction_order_proofs WHERE intent_id=?',(row['intent_id'],)).fetchone()
                m=metadata.get(ex.execution_id)
                if p is None or m is None or p['perm_id'] is None or (m['perm_id'],m['account'],m['currency'],m['security_type'],m['ticker']) != (p['perm_id'],ACCOUNT,'USD','STK',TICKER):
                    self.stop('Missing/inconsistent execution proof')
                with self.store.tx() as db:
                    db.execute('INSERT OR REPLACE INTO auction_execution_proofs VALUES(?,?,?,?,?)',
                               (ex.execution_id,row['intent_id'],json.dumps(m),json.dumps(fees.get(ex.execution_id)) if ex.execution_id in fees else None,now()))
            self.store.sync_execution(ex)
        local={t:r['quantity'] for t,r in self.store.positions(ACCOUNT).items()}
        actual={t:p.quantity for t,p in s.positions.items() if p.quantity}
        if any(p.quantity<=0 or not math.isfinite(p.market_value) for p in s.positions.values()) or local!=actual:
            self.stop('SQLite/broker positions disagree')
        open_refs={o.intent_id for o in s.open_orders}
        for proof in self.store.db.execute('SELECT * FROM auction_order_proofs WHERE session=?',(self.day,)):
            intent=self.store.intent(proof['intent_id'])
            if intent['status'] in ('PLANNED','SUBMITTING','SENT','ACKNOWLEDGED','PARTIAL') and proof['intent_id'] not in open_refs:
                self.stop('Order absent without verified terminal/fill evidence')
            if proof['broker_status']=='Filled' and intent['status']!='FILLED':self.stop('Filled status without execution evidence')
        for active in self.store.active_intents():
            if active['intent_id'] not in refs:self.stop('Unexpected active SQLite intent')
        for o in s.open_orders:
            p=self.store.db.execute('SELECT * FROM auction_order_proofs WHERE intent_id=?',(o.intent_id,)).fetchone()
            if p is None or o.broker_order_id!=p['broker_order_id']:self.stop('Unrecognized test open order')
        if not math.isfinite(s.available_cash) or s.available_cash<0:self.stop('Invalid verified cash')
        return s

    def filled(self,side):
        row=self.store.intent(self.ref(side))
        if row is None or row['status']!='FILLED':return False
        proofs=self.store.db.execute('SELECT metadata_json FROM auction_execution_proofs WHERE intent_id=?',(self.ref(side),)).fetchall()
        executions=self.store.db.execute('SELECT quantity FROM executions WHERE intent_id=?',(self.ref(side),)).fetchall()
        if not proofs or sum(r['quantity'] for r in executions)!=1:self.stop('Missing one-share fill proof')
        opening,closing=schedule(self.day)
        start=opening if side=='BUY' else closing
        end=start+pd.Timedelta(minutes=5 if side=='BUY' else 10)
        for p in proofs:
            m=json.loads(p['metadata_json'])
            verify_auction_time(SimpleNamespace(fill_times={m['oid']:m['exchange_time']},audit=self.broker.audit),m['oid'],side,start,end)
        return True

    def submit(self,intent):
        if not self.settings.trading_enabled or self.broker.stop_path.exists():self.stop('Kill switch/trading disabled')
        if self.store.intent(intent.intent_id):self.stop('Existing intent; no resubmission')
        oid=self.broker.reserve(intent)
        self.store.save_intent(intent,'PLANNED')
        if not self.store.order_claim(intent.intent_id,ACCOUNT):self.stop('Duplicate claim')
        self.store.order_ack(intent.intent_id,oid,'SUBMITTING')
        with self.store.tx() as db:
            db.execute('INSERT INTO auction_order_proofs VALUES(?,?,?,?,?,?,?,?,?)',
                       (intent.intent_id,self.day,intent.side,oid,None,0,None,None,now()))
        self.state('ENTRY_SUBMITTING' if intent.side=='BUY' else 'EXIT_SUBMITTING')
        self.broker.send(intent,oid)
        # Explicit reconnect: do not rely on callbacks from the original process/connection.
        self.broker.close()
        self.recover()
        proof=self.store.db.execute('SELECT * FROM auction_order_proofs WHERE intent_id=?',(intent.intent_id,)).fetchone()
        if not proof['acknowledged'] or proof['perm_id'] is None:self.stop('No broker-host acknowledgement')
        row=self.store.intent(intent.intent_id)
        if row['status'] in ('REJECTED','CANCELLED'):self.stop('Order '+row['status'])

    def run(self,phase):
        if phase not in ('enter','arm-exit','verify-close'):raise ValueError('Unknown checkpoint')
        s=self.recover()
        existing=self.store.intent(self.ref('BUY' if phase=='enter' else 'SELL'))
        if phase=='enter':
            if existing:
                if existing['status'] not in ('ACKNOWLEDGED','FILLED'):self.stop('Existing entry is not accepted/filled')
                self.state('ENTRY_FILLED' if existing['status']=='FILLED' else 'ENTRY_ACCEPTED')
                return dict(phase=phase,idempotent=True,order_ref=existing['intent_id'],status=existing['status'])
            phase_window(phase,self.day,self.at)
            reference=self.broker.reference()
            limit=safe_limit(reference)
            guard_snapshot(s,'BUY',limit,self.settings.cash_buffer_usd)
            signal=Signal(STRATEGY,TICKER,self.day,self.day,self.day,reference,'Isolated disconnected auction test',1)
            candidate,reason=entry_intent(signal,self.store,s,self.settings)
            if reason:self.stop('Risk preflight: '+reason)
            i=replace(candidate,intent_id=self.ref('BUY'),quantity=1,limit_price=min(limit,candidate.limit_price))
            self.store.register(STRATEGY,'bot.auction_validation')
            self.broker.audit.emit('LIMIT_CHECK',reference_close=reference,calculated_limit=i.limit_price,current_ibkr_ceiling=None)
            self.submit(i)
            self.state('ENTRY_ACCEPTED')
        elif phase=='arm-exit':
            if existing:
                if existing['status'] not in ('ACKNOWLEDGED','FILLED'):self.stop('Existing exit uncertain/rejected/cancelled')
                self.state('EXIT_FILLED' if existing['status']=='FILLED' else 'EXIT_ACCEPTED')
                return dict(phase=phase,idempotent=True,order_ref=existing['intent_id'],status=existing['status'])
            phase_window(phase,self.day,self.at)
            if not self.filled('BUY'):self.stop('OPG is not Filled; no SELL allowed')
            guard_snapshot(s,'SELL')
            position=self.store.position(ACCOUNT,TICKER)
            if position['strategy_id']!=STRATEGY or position['entry_session']!=self.day:self.stop('Position not this test')
            i=OrderIntent(self.ref('SELL'),STRATEGY,TICKER,'SELL',1,self.day,'PAPER_TEST_MOC',now(),1,self.day,'MOC',None,ACCOUNT,position['avg_entry_price'])
            self.submit(i)
            self.state('EXIT_ACCEPTED')
        else:
            phase_window(phase,self.day,self.at)
            buy_filled,sell_filled=self.filled('BUY'),self.filled('SELL')
            flat=not s.positions and not s.open_orders and not self.store.positions(ACCOUNT)
            result=dict(phase=phase,OPG='PASS' if buy_filled else 'FAIL',
                        MOC='PASS' if sell_filled and flat else 'FAIL',
                        positions={t:p.quantity for t,p in s.positions.items()},open_orders=len(s.open_orders),reconciliation='PASS')
            if buy_filled and sell_filled and flat:result['positions']=0
            result['orders']=[dict(r) for r in self.store.db.execute('SELECT * FROM auction_order_proofs WHERE session=?',(self.day,))]
            result['executions']=[dict(r) for r in self.store.db.execute('SELECT e.*,p.metadata_json,p.fees_json FROM executions e JOIN auction_execution_proofs p USING(execution_id) WHERE e.intent_id IN (?,?)',(self.ref('BUY'),self.ref('SELL')))]
            self.state('CLOSED' if result['OPG']==result['MOC']=='PASS' else 'FAILED',result)
            return result
        proof=dict(self.store.db.execute('SELECT * FROM auction_order_proofs WHERE intent_id=?',(i.intent_id,)).fetchone())
        return dict(phase=phase,status='ACCEPTED',order=proof,reconciliation='PASS')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('enter','arm-exit','verify-close'))
    parser.add_argument('--session',required=True)
    args=parser.parse_args()
    if os.getenv('TRADING_MODE','PAPER').upper()!='PAPER':raise ValueError('LIVE/DRY_RUN not allowed for auction workflow')
    if os.getenv('IBKR_ALLOWED_ACCOUNT_ID',ACCOUNT)!=ACCOUNT:raise ValueError('Exact account allowlist required')
    settings=Settings(allowed_account_id=ACCOUNT,ibkr_port=int(os.getenv('IBKR_PORT','4002')),
                      ibkr_client_id=82,trading_enabled=os.getenv('TRADING_ENABLED','false').lower()=='true',
                      db_path=Path(os.getenv('BOT_DB_PATH',str(Settings.db_path)))).validate()
    store=Store(settings.db_path)
    audit=Audit(store.path.parent/('auction_'+args.session+'.jsonl'))
    broker=AuctionBroker(settings,audit,args.session)
    run=store.run_start('auction_'+args.phase,'PAPER',args.session)
    try:
        workflow=Checkpoints(store,broker,settings,args.session)
        result=workflow.run(args.phase)
        audit.emit('CHECKPOINT_COMPLETE',**result)
        if args.phase=='verify-close':
            report_path=store.path.parent/('auction_'+args.session+'_report.json')
            report_path.write_text(json.dumps(result,indent=2))
        if audit.failed:raise RuntimeError('Audit unavailable')
        failed=args.phase=='verify-close' and (result.get('OPG')!='PASS' or result.get('MOC')!='PASS')
        store.run_end(run,'FAILED' if failed else 'OK',result)
        return 2 if failed else 0
    except Exception as exc:
        audit.emit('STOP',error=str(exc))
        store.error(run,'AUCTION_STOP',str(exc));store.run_end(run,'FAILED',dict(error=str(exc)))
        raise
    finally:
        broker.close();store.close()
