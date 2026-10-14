"""SQLite decision ledger. Submission ambiguity is preserved, never retried blind."""
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
import math
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30)
        self.db.row_factory=sqlite3.Row
        self._run_lock_handle=None
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.init()

    def close(self):
        self._release_run_lock()
        self.db.close()

    def _release_run_lock(self):
        if self._run_lock_handle is not None:
            fcntl.flock(self._run_lock_handle,fcntl.LOCK_UN)
            self._run_lock_handle.close();self._run_lock_handle=None

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def init(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS strategies(strategy_id TEXT PRIMARY KEY,source TEXT NOT NULL,registered_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signals(strategy_id TEXT NOT NULL,ticker TEXT NOT NULL,signal_date TEXT NOT NULL,
            entry_date TEXT NOT NULL,exit_date TEXT NOT NULL,reference_close REAL NOT NULL,reason TEXT NOT NULL,
            created_at TEXT NOT NULL,PRIMARY KEY(strategy_id,ticker,signal_date));
        CREATE TABLE IF NOT EXISTS order_intents(intent_id TEXT PRIMARY KEY,strategy_id TEXT NOT NULL,ticker TEXT NOT NULL,
            side TEXT NOT NULL,quantity INTEGER NOT NULL,intended_entry_date TEXT NOT NULL,target_exit_date TEXT NOT NULL,
            account_id TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,holding_sessions INTEGER NOT NULL,
            order_type TEXT NOT NULL,limit_price REAL,reference_close REAL NOT NULL,status TEXT NOT NULL,refusal_reason TEXT);
        CREATE TABLE IF NOT EXISTS orders(intent_id TEXT PRIMARY KEY,broker_order_id INTEGER UNIQUE,account_id TEXT NOT NULL,
            status TEXT NOT NULL,filled_qty INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,
            FOREIGN KEY(intent_id) REFERENCES order_intents(intent_id));
        CREATE TABLE IF NOT EXISTS executions(execution_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL,broker_order_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,side TEXT NOT NULL,quantity INTEGER NOT NULL,price REAL NOT NULL,session TEXT NOT NULL,
            account_id TEXT NOT NULL,received_at TEXT NOT NULL,benchmark_price REAL,fill_deviation_bps REAL,
            benchmark_side TEXT,FOREIGN KEY(intent_id) REFERENCES order_intents(intent_id));
        CREATE TABLE IF NOT EXISTS positions(account_id TEXT NOT NULL,ticker TEXT NOT NULL,strategy_id TEXT NOT NULL,
            quantity INTEGER NOT NULL,entry_session TEXT NOT NULL,exit_session TEXT NOT NULL,avg_entry_price REAL NOT NULL,
            PRIMARY KEY(account_id,ticker));
        CREATE TABLE IF NOT EXISTS daily_runs(run_id TEXT PRIMARY KEY,kind TEXT NOT NULL,mode TEXT NOT NULL,asof TEXT,
            started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL,summary_json TEXT);
        CREATE TABLE IF NOT EXISTS errors(error_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,code TEXT NOT NULL,
            message TEXT NOT NULL,at_utc TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations_state(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL,
            updated_at TEXT NOT NULL,last_execution TEXT,last_error TEXT);
        CREATE TABLE IF NOT EXISTS operations_control(id INTEGER PRIMARY KEY CHECK(id=1),dry_run_enabled INTEGER NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO operations_control(id,dry_run_enabled) VALUES(1,0);
        CREATE TABLE IF NOT EXISTS safety_control(id INTEGER PRIMARY KEY CHECK(id=1),kill_switch INTEGER NOT NULL DEFAULT 0,
            activated_at TEXT,source TEXT);
        INSERT OR IGNORE INTO safety_control(id,kill_switch) VALUES(1,0);
        CREATE TABLE IF NOT EXISTS notification_outbox(event_key TEXT PRIMARY KEY,kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,created_at TEXT NOT NULL,sent_at TEXT);
        CREATE TABLE IF NOT EXISTS notification_failures(event_key TEXT PRIMARY KEY,status TEXT NOT NULL,
            at_utc TEXT NOT NULL,FOREIGN KEY(event_key) REFERENCES notification_outbox(event_key));
        CREATE TABLE IF NOT EXISTS telegram_poll_state(id INTEGER PRIMARY KEY CHECK(id=1),last_update_id INTEGER NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO telegram_poll_state(id,last_update_id) VALUES(1,0);
        ''')
        cols={r[1] for r in self.db.execute('PRAGMA table_info(executions)')}
        for col,kind in [('benchmark_price','REAL'),('fill_deviation_bps','REAL'),('benchmark_side','TEXT')]:
            if col not in cols:self.db.execute(f'ALTER TABLE executions ADD COLUMN {col} {kind}')
        self.db.commit()

    def register(self,strategy_id,source):
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO strategies VALUES(?,?,?)',(strategy_id,source,now()))

    def run_start(self,kind,mode,asof=None):
        if self._run_lock_handle is not None:raise RuntimeError('A bot run is already active in this process')
        handle=open(str(self.path)+'.run.lock','a')
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close();raise RuntimeError('Another bot run is active; refusing concurrent orders')
        self._run_lock_handle=handle
        run_id=uuid.uuid4().hex
        try:
            with self.tx() as db:
                # A live run holds this same lock. Only its next owner may
                # classify abandoned diagnostics; never infer broker fills.
                db.execute("UPDATE daily_runs SET status='INTERRUPTED',ended_at=?,summary_json=COALESCE(summary_json,?) WHERE status='RUNNING'",
                           (now(),json.dumps(dict(error='PROCESS_INTERRUPTED'))))
                db.execute('INSERT INTO daily_runs(run_id,kind,mode,asof,started_at,status) VALUES(?,?,?,?,?,?)',
                           (run_id,kind,mode,asof,now(),'RUNNING'))
        except Exception:
            self._release_run_lock();raise
        return run_id

    def run_end(self,run_id,status,summary=None):
        try:
            with self.tx() as db:
                db.execute('UPDATE daily_runs SET ended_at=?,status=?,summary_json=? WHERE run_id=?',
                           (now(),status,json.dumps(summary or {},sort_keys=True),run_id))
                row=db.execute('SELECT kind,asof,mode FROM daily_runs WHERE run_id=?',(run_id,)).fetchone()
                if row and row['kind']=='daily' and status=='OK' and row['asof']:
                    closures=[json.loads(r[0]) for r in db.execute(
                        "SELECT payload_json FROM notification_outbox WHERE kind='closed'")]
                    realized=sum(p['pnl_usd'] for p in closures if p.get('session')==row['asof'])
                    critical=db.execute('SELECT COUNT(*) FROM errors WHERE run_id=?',(run_id,)).fetchone()[0]
                    position_count=db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
                    if row['mode']=='DRY_RUN' and db.execute("SELECT 1 FROM sqlite_master WHERE name='simulated_positions'").fetchone():
                        position_count=db.execute('SELECT COUNT(*) FROM simulated_positions').fetchone()[0]
                    self._enqueue(db,'daily:'+row['mode']+':'+row['asof'],'daily',
                                  dict(session=row['asof'],positions=position_count,
                                       realized_pnl_usd=realized,critical_errors=critical,unrealized_pct=None))
        finally:
            self._release_run_lock()

    def error(self,run_id,code,message):
        with self.tx() as db:
            cursor=db.execute('INSERT INTO errors(run_id,code,message,at_utc) VALUES(?,?,?,?)',(run_id,code,str(message),now()))
            if code in ('RECONCILIATION_REQUIRED','RUN_FAILED','DATA_ERROR'):
                kind='reconciliation' if code=='RECONCILIATION_REQUIRED' else 'critical_error'
                self._enqueue(db,'error:'+str(cursor.lastrowid),kind,dict(code=code))

    def save_signal(self,s):
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?,?)',
                       (s.strategy_id,s.ticker,s.signal_date,s.entry_date,s.exit_date,s.reference_close,s.reason,now()))

    def save_intent(self,intent,status,refusal_reason=None):
        with self.tx() as db:
            db.execute('''INSERT OR IGNORE INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (intent.intent_id,intent.strategy_id,intent.ticker,intent.side,intent.quantity,
                        intent.intended_entry_date,intent.target_exit_date,intent.account_id,intent.reason,
                        intent.timestamp_utc,intent.expected_holding_sessions,intent.order_type,intent.limit_price,
                        intent.reference_close,status,refusal_reason))
        return self.intent(intent.intent_id)

    def intent(self,intent_id):
        return self.db.execute('SELECT * FROM order_intents WHERE intent_id=?',(intent_id,)).fetchone()

    def active_intents(self):
        return self.db.execute("SELECT * FROM order_intents WHERE status IN ('PLANNED','SUBMITTING','SENT','ACKNOWLEDGED','PARTIAL')").fetchall()

    def orders_on(self,day,ignore_intent_id=None):
        return self.db.execute("SELECT count(*) FROM order_intents WHERE intended_entry_date=? AND status NOT IN ('REFUSED','DRY_RUN') AND intent_id!=?",(day,ignore_intent_id or '')).fetchone()[0]

    def due_exits_on(self,account,day):
        return self.db.execute('SELECT count(*) FROM positions WHERE account_id=? AND exit_session=?',(account,day)).fetchone()[0]

    def positions(self,account):
        return {r['ticker']:r for r in self.db.execute('SELECT * FROM positions WHERE account_id=?',(account,))}

    def position(self,account,ticker):
        return self.db.execute('SELECT * FROM positions WHERE account_id=? AND ticker=?',(account,ticker)).fetchone()

    def order_claim(self,intent_id,account):
        """Durable state before network I/O. A crash here requires reconciliation."""
        with self.tx() as db:
            if db.execute('SELECT kill_switch FROM safety_control WHERE id=1').fetchone()[0]:
                return False
            row=db.execute('SELECT status,account_id FROM order_intents WHERE intent_id=?',(intent_id,)).fetchone()
            if not row or row['status']!='PLANNED' or row['account_id']!=account:
                return False
            db.execute("UPDATE order_intents SET status='SUBMITTING' WHERE intent_id=?",(intent_id,))
            db.execute('INSERT INTO orders(intent_id,account_id,status,updated_at) VALUES(?,?,?,?)',
                       (intent_id,account,'SUBMITTING',now()))
            return True

    def order_ack(self,intent_id,broker_order_id,status='SENT'):
        with self.tx() as db:
            db.execute('UPDATE orders SET broker_order_id=?,status=?,updated_at=? WHERE intent_id=?',
                       (broker_order_id,status,now(),intent_id))
            db.execute('UPDATE order_intents SET status=? WHERE intent_id=?',(status,intent_id))

    def bind_open_order(self,order):
        row=self.intent(order.intent_id)
        if row is None or row['account_id']!=order.account_id:
            raise RuntimeError('RECONCILIATION_REQUIRED: unknown broker order')
        if (row['ticker'],row['side'],row['quantity']) != (order.ticker,order.side,order.quantity):
            raise RuntimeError('RECONCILIATION_REQUIRED: broker order terms changed')
        existing=self.db.execute('SELECT broker_order_id,status FROM orders WHERE intent_id=?',(order.intent_id,)).fetchone()
        if existing and existing['broker_order_id'] not in (None,order.broker_order_id):
            raise RuntimeError('RECONCILIATION_REQUIRED: order ID mismatch')
        if not existing:
            raise RuntimeError('RECONCILIATION_REQUIRED: broker order without local claim')
        if existing['status']=='FILLED':
            raise RuntimeError('RECONCILIATION_REQUIRED: filled order still open')
        self.order_ack(order.intent_id,order.broker_order_id,
                       'PARTIAL' if existing['status']=='PARTIAL' else 'ACKNOWLEDGED')

    def sync_execution(self,execution):
        with self.tx() as db:
            previous=db.execute('SELECT * FROM executions WHERE execution_id=?',(execution.execution_id,)).fetchone()
            if previous:
                fields=('broker_order_id','ticker','side','quantity','price','session','account_id')
                if any(previous[name]!=getattr(execution,name) for name in fields):
                    raise RuntimeError('RECONCILIATION_REQUIRED: conflicting execution evidence')
                return False
            order=db.execute('''SELECT o.intent_id,i.strategy_id,i.side,i.target_exit_date,i.intended_entry_date,
                   i.quantity,i.ticker FROM orders o JOIN order_intents i USING(intent_id)
                   WHERE o.broker_order_id=? AND o.account_id=?''',(execution.broker_order_id,execution.account_id)).fetchone()
            if order is None or order['ticker']!=execution.ticker or order['side']!=execution.side:
                raise RuntimeError('RECONCILIATION_REQUIRED: unrecognized execution')
            if (not math.isfinite(execution.quantity) or execution.quantity<=0 or execution.quantity!=int(execution.quantity)
                    or not math.isfinite(execution.price) or execution.price<=0 or execution.side not in ('BUY','SELL')):
                raise ValueError('Invalid broker execution')
            already=db.execute('SELECT COALESCE(SUM(quantity),0) FROM executions WHERE intent_id=?',(order['intent_id'],)).fetchone()[0]
            if already+execution.quantity>order['quantity']:
                raise RuntimeError('RECONCILIATION_REQUIRED: execution exceeds order quantity')
            db.execute('''INSERT INTO executions(execution_id,intent_id,broker_order_id,ticker,side,quantity,price,session,
                       account_id,received_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                       (execution.execution_id,order['intent_id'],execution.broker_order_id,execution.ticker,
                        execution.side,execution.quantity,execution.price,execution.session,execution.account_id,now()))
            pos=db.execute('SELECT * FROM positions WHERE account_id=? AND ticker=?',(execution.account_id,execution.ticker)).fetchone()
            if execution.side=='BUY':
                if execution.session != order['intended_entry_date']:
                    raise RuntimeError('RECONCILIATION_REQUIRED: entry filled outside intended session')
                if pos is not None and (pos['strategy_id']!=order['strategy_id'] or pos['entry_session']!=execution.session):
                    raise RuntimeError('RECONCILIATION_REQUIRED: buy overlaps existing position')
                qty=(pos['quantity'] if pos else 0)+execution.quantity
                avg=((pos['quantity']*pos['avg_entry_price'] if pos else 0)+execution.quantity*execution.price)/qty
                db.execute('INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?,?)',
                           (execution.account_id,execution.ticker,order['strategy_id'],qty,execution.session,
                            order['target_exit_date'],avg))
                if pos is None:
                    self._enqueue(db,'open:'+execution.account_id+':'+execution.ticker+':'+execution.session,
                                  'opened',dict(ticker=execution.ticker,price=avg,quantity=qty,
                                                notional_usd=qty*avg,strategy=order['strategy_id']))
            else:
                if execution.session != order['target_exit_date']:
                    raise RuntimeError('RECONCILIATION_REQUIRED: exit filled outside intended session')
                if pos is None or execution.quantity>pos['quantity']:
                    raise RuntimeError('RECONCILIATION_REQUIRED: exit exceeds recorded position')
                qty=pos['quantity']-execution.quantity
                if qty:
                    db.execute('UPDATE positions SET quantity=? WHERE account_id=? AND ticker=?',(qty,execution.account_id,execution.ticker))
                else:
                    db.execute('DELETE FROM positions WHERE account_id=? AND ticker=?',(execution.account_id,execution.ticker))
                    aggregate=db.execute('SELECT SUM(quantity),SUM(quantity*price) FROM executions WHERE intent_id=?',
                                         (order['intent_id'],)).fetchone()
                    closed_qty=int(aggregate[0]);exit_price=float(aggregate[1])/closed_qty
                    pnl=float(aggregate[1])-closed_qty*pos['avg_entry_price']
                    self._enqueue(db,'close:'+order['intent_id'],'closed',
                                  dict(ticker=execution.ticker,price=exit_price,quantity=closed_qty,
                                       pnl_usd=pnl,pnl_pct=(exit_price/pos['avg_entry_price']-1)*100,
                                       session=execution.session,strategy=order['strategy_id']))
            filled=db.execute('SELECT SUM(quantity) FROM executions WHERE intent_id=?',(order['intent_id'],)).fetchone()[0]
            status='FILLED' if filled>=order['quantity'] else 'PARTIAL'
            db.execute('UPDATE orders SET filled_qty=?,status=?,updated_at=? WHERE intent_id=?',(filled,status,now(),order['intent_id']))
            db.execute('UPDATE order_intents SET status=? WHERE intent_id=?',(status,order['intent_id']))
            return True

    def missing_benchmarks(self,asof):
        return self.db.execute('SELECT execution_id,ticker,side,price,session FROM executions WHERE benchmark_price IS NULL AND session<=?',(asof,)).fetchall()

    def record_benchmark(self,execution_id,price,side):
        if price<=0:raise ValueError('Invalid unadjusted benchmark price')
        with self.tx() as db:
            row=db.execute('SELECT side,price FROM executions WHERE execution_id=?',(execution_id,)).fetchone()
            if row is None:raise ValueError('Unknown execution')
            deviation=(row['price']/price-1)*10000
            if row['side']=='SELL':deviation=-deviation
            db.execute('UPDATE executions SET benchmark_price=?,fill_deviation_bps=?,benchmark_side=? WHERE execution_id=?',
                       (price,deviation,side,execution_id))

    def executions_since_run(self,run_id):
        return self.db.execute('''SELECT count(*) FROM executions WHERE received_at >=
             (SELECT started_at FROM daily_runs WHERE run_id=?)''',(run_id,)).fetchone()[0]

    def summary(self):
        return dict(positions=[dict(x) for x in self.db.execute('SELECT * FROM positions ORDER BY ticker')],
                    pending=[dict(x) for x in self.db.execute("SELECT intent_id,ticker,side,status,intended_entry_date,target_exit_date FROM order_intents WHERE status IN ('PLANNED','SUBMITTING','SENT','ACKNOWLEDGED','PARTIAL') ORDER BY created_at")],
                    recent_executions=[dict(x) for x in self.db.execute('SELECT execution_id,ticker,side,quantity,price,session,benchmark_price,fill_deviation_bps FROM executions ORDER BY received_at DESC LIMIT 10')],
                    recent_runs=[dict(x) for x in self.db.execute('SELECT run_id,kind,asof,status,summary_json FROM daily_runs ORDER BY started_at DESC LIMIT 5')],
                    recent_errors=[dict(x) for x in self.db.execute('SELECT code,message,at_utc FROM errors ORDER BY error_id DESC LIMIT 5')])

    def operations_state(self):
        row=self.db.execute('SELECT * FROM operations_state WHERE id=1').fetchone()
        return dict(row) if row else None

    def set_operations_state(self,state,last_execution=None,last_error=None):
        valid={'RUNNING','READY','DISABLED','BROKER_DISCONNECTED','RECONCILIATION_REQUIRED',
               'DATA_ERROR','ORDER_BLOCKED','ERROR'}
        if state not in valid:raise ValueError('Invalid bot state')
        with self.tx() as db:
            db.execute('''INSERT INTO operations_state VALUES(1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,
                last_execution=COALESCE(excluded.last_execution,operations_state.last_execution),
                last_error=excluded.last_error''',(state,now(),last_execution,last_error))

    def dry_run_enabled(self):
        return bool(self.db.execute('SELECT dry_run_enabled FROM operations_control WHERE id=1').fetchone()[0])

    def set_dry_run_enabled(self,enabled):
        with self.tx() as db:
            if enabled and db.execute('SELECT kill_switch FROM safety_control WHERE id=1').fetchone()[0]:
                raise ValueError('KILL_SWITCH_ACTIVE')
            db.execute('UPDATE operations_control SET dry_run_enabled=? WHERE id=1',(int(bool(enabled)),))

    @contextmanager
    def order_gate(self):
        """Serialize network submission with /kill across processes."""
        handle=open(str(self.path)+'.order_gate.lock','a')
        try:
            fcntl.flock(handle,fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)
            handle.close()

    def kill_switch_enabled(self):
        return bool(self.db.execute('SELECT kill_switch FROM safety_control WHERE id=1').fetchone()[0])

    def activate_kill_switch(self,source='telegram'):
        with self.order_gate():
            with self.tx() as db:
                if db.execute('SELECT kill_switch FROM safety_control WHERE id=1').fetchone()[0]:
                    return False
                db.execute('UPDATE safety_control SET kill_switch=1,activated_at=?,source=? WHERE id=1',
                           (now(),source))
                db.execute('UPDATE operations_control SET dry_run_enabled=0 WHERE id=1')
                if source!='telegram':
                    self._enqueue(db,'kill:'+now(),'kill',dict(source=source))
                db.execute('INSERT INTO errors(run_id,code,message,at_utc) VALUES(NULL,?,?,?)',
                           ('KILL_SWITCH_ACTIVATED','Kill switch activated by authorized command',now()))
                return True

    def reset_kill_switch_local(self):
        """Local operator action only; no Telegram resume command."""
        with self.order_gate():
            with self.tx() as db:
                db.execute('UPDATE safety_control SET kill_switch=0,activated_at=NULL,source=NULL WHERE id=1')
                db.execute('INSERT INTO errors(run_id,code,message,at_utc) VALUES(NULL,?,?,?)',
                           ('KILL_SWITCH_RESET','Kill switch reset by local operator',now()))

    @staticmethod
    def _enqueue(db,key,kind,payload):
        db.execute('INSERT OR IGNORE INTO notification_outbox VALUES(?,?,?,?,NULL)',
                   (key,kind,json.dumps(payload,sort_keys=True),now()))

    def pending_notifications(self,limit=20):
        return [dict(row) for row in self.db.execute(
            '''SELECT * FROM notification_outbox o WHERE sent_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM notification_failures f WHERE f.event_key=o.event_key)
               ORDER BY created_at,event_key LIMIT ?''',
            (limit,))]

    def fail_notification(self,key):
        """Keep malformed evidence undelivered, without blocking later alerts."""
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO notification_failures VALUES(?,?,?)',(key,'INVALID_PAYLOAD',now()))
            db.execute('INSERT INTO errors(run_id,code,message,at_utc) VALUES(NULL,?,?,?)',
                       ('NOTIFICATION_INVALID','Invalid notification quarantined; no payload logged',now()))
            self._enqueue(db,'invalid-notification:'+key,'critical_error',dict(code='NOTIFICATION_INVALID'))

    def mark_notification_sent(self,key):
        with self.tx() as db:
            db.execute('UPDATE notification_outbox SET sent_at=? WHERE event_key=? AND sent_at IS NULL',(now(),key))

    def telegram_offset(self):
        return self.db.execute('SELECT last_update_id FROM telegram_poll_state WHERE id=1').fetchone()[0]

    def mark_telegram_update(self,update_id):
        with self.tx() as db:
            db.execute('UPDATE telegram_poll_state SET last_update_id=MAX(last_update_id,?) WHERE id=1',
                       (int(update_id),))
