"""DRY_RUN-only accounting. Never writes broker orders/executions/positions."""
import math

import pandas as pd

from .calendar import last_complete_session
from .models import BrokerSnapshot, BrokerPosition
from .portfolio import entry_intent
from .storage import now


def require_dry_run(store,settings):
    settings.validate()
    if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
        raise ValueError('Cloud V1 is DRY_RUN only; all broker orders forbidden')
    # The deployment must not reuse the existing Paper ledger, even when flat.
    for table in ('orders','executions','positions'):
        if store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:
            raise ValueError('Cloud DRY_RUN requires a separate ledger without broker history')
    if store.db.execute("SELECT 1 FROM order_intents WHERE account_id!='DRY_RUN' LIMIT 1").fetchone():
        raise ValueError('Non-simulated account in DRY_RUN ledger')
    if store.db.execute("SELECT 1 FROM order_intents WHERE status NOT IN ('DRY_RUN','REFUSED','SIMULATED_NO_FILL','SIMULATED_CLOSED') LIMIT 1").fetchone():
        raise ValueError('Unknown or broker submission state in DRY_RUN ledger')


def initialize(store,settings):
    require_dry_run(store,settings)
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS simulated_fills(intent_id TEXT NOT NULL,side TEXT NOT NULL,
      ticker TEXT NOT NULL,quantity INTEGER NOT NULL,price REAL NOT NULL,session TEXT NOT NULL,
      observed_at TEXT NOT NULL,PRIMARY KEY(intent_id,side));
    CREATE TABLE IF NOT EXISTS simulated_positions(ticker TEXT PRIMARY KEY,strategy_id TEXT NOT NULL,
      quantity INTEGER NOT NULL,entry_session TEXT NOT NULL,exit_session TEXT NOT NULL,avg_entry_price REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS deployment_health(key TEXT PRIMARY KEY,value TEXT NOT NULL,observed_at TEXT NOT NULL);
    ''')
    store.db.commit()


def positions(store):
    return [dict(row) for row in store.db.execute('SELECT * FROM simulated_positions ORDER BY ticker')]


def reconcile(store,settings):
    require_dry_run(store,settings)
    quantities={r['ticker']:r['quantity'] for r in store.db.execute("SELECT ticker,SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END) AS quantity FROM simulated_fills GROUP BY ticker") if r['quantity']}
    held={p['ticker']:p['quantity'] for p in positions(store)}
    if quantities!=held or any(q<=0 for q in held.values()):raise ValueError('Simulated ledger mismatch')
    if store.db.execute("SELECT 1 FROM simulated_fills f LEFT JOIN order_intents i USING(intent_id) WHERE i.intent_id IS NULL OR i.ticker!=f.ticker OR i.quantity!=f.quantity LIMIT 1").fetchone():raise ValueError('Invalid simulated fill provenance')
    return dict(status='PASS',scope='SIMULATION_ONLY',broker='DISABLED_BY_DRY_RUN_POLICY',positions=len(held))


def risk_snapshot(store,settings):
    # A model snapshot for the existing portfolio checks; not a broker snapshot.
    held={p['ticker']:BrokerPosition(p['ticker'],p['quantity'],p['quantity']*p['avg_entry_price']) for p in positions(store)}
    cash=settings.initial_equity_usd
    for row in store.db.execute('SELECT side,quantity,price FROM simulated_fills'):
        cash+=(-1 if row['side']=='BUY' else 1)*row['quantity']*row['price']
    for row in store.db.execute("SELECT * FROM order_intents i WHERE status='DRY_RUN' AND NOT EXISTS (SELECT 1 FROM simulated_fills f WHERE f.intent_id=i.intent_id AND f.side='BUY')"):
        if row['ticker'] in held:raise ValueError('Duplicate simulated exposure')
        held[row['ticker']]=BrokerPosition(row['ticker'],row['quantity'],row['quantity']*row['limit_price'])
        cash-=row['quantity']*row['limit_price']+settings.cash_buffer_usd
    return BrokerSnapshot('DRY_RUN',max(0,cash),held)


def plan(store,settings,strategy,frame,day):
    initialize(store,settings)
    if store.kill_switch_enabled():raise ValueError('KILL_SWITCH_ACTIVE')
    reconcile(store,settings)
    signals=strategy.generate_signals(frame,day)
    store.register(strategy.strategy_id,'results/research_v2/frozen_candidates.json')
    result=dict(signals=len(signals),accepted=0,refused=0,orders_sent=0,decisions=[])
    for signal in sorted(signals,key=lambda s:s.ticker):
        with store.order_gate():
            if store.kill_switch_enabled():raise ValueError('KILL_SWITCH_ACTIVE')
            store.save_signal(signal)
            count=store.db.execute("SELECT COUNT(*) FROM order_intents WHERE intended_entry_date=? AND status='DRY_RUN'",(signal.entry_date,)).fetchone()[0]
            count+=sum(p['exit_session']==signal.entry_date for p in positions(store))
            intent,reason=entry_intent(signal,store,risk_snapshot(store,settings),settings)
            if count>=settings.max_orders_per_day:reason='MAX_ORDERS_PER_DAY'
            if reason:
                result['refused']+=1;result['decisions'].append(dict(ticker=signal.ticker,accepted=False,reason=reason));continue
            if store.intent(intent.intent_id):continue
            store.save_intent(intent,'DRY_RUN');result['accepted']+=1
            result['decisions'].append(dict(ticker=intent.ticker,accepted=True,intent_id=intent.intent_id,
                                           quantity=intent.quantity,intended_entry_date=intent.intended_entry_date,
                                           exit_date=intent.target_exit_date))
    return result


def settle(store,settings,frame,day,at=None):
    with store.order_gate():
        return _settle(store,settings,frame,day,at)


def _settle(store,settings,frame,day,at=None):
    initialize(store,settings)
    if store.kill_switch_enabled():raise ValueError('KILL_SWITCH_ACTIVE')
    if day>last_complete_session(at):raise ValueError('Simulation requires completed bars')
    reconcile(store,settings)
    if any(p['exit_session']<day for p in positions(store)):raise ValueError('Missed simulated exit; operator required')
    if store.db.execute("SELECT 1 FROM order_intents i WHERE status='DRY_RUN' AND intended_entry_date<? AND NOT EXISTS (SELECT 1 FROM simulated_fills f WHERE f.intent_id=i.intent_id AND f.side='BUY') LIMIT 1",(day,)).fetchone():raise ValueError('Missed simulated entry; operator required')
    bars=frame[frame.Date.eq(pd.Timestamp(day))].set_index('Ticker')
    if bars.index.has_duplicates:raise ValueError('Duplicate market bars')
    result=dict(simulated_entries=0,simulated_exits=0,orders_sent=0,observation='AFTER_CLOSE_COMPLETED_DAILY_BAR')
    plans=store.db.execute("SELECT * FROM order_intents WHERE status='DRY_RUN' AND intended_entry_date=? ORDER BY ticker",(day,)).fetchall()
    for intent in plans:
        if store.db.execute("SELECT 1 FROM simulated_fills WHERE intent_id=? AND side='BUY'",(intent['intent_id'],)).fetchone():continue
        if intent['ticker'] not in bars.index:raise ValueError('Missing entry simulation bar')
        price=float(bars.loc[intent['ticker'],'Open'])
        if not math.isfinite(price) or price<=0:raise ValueError('Invalid simulated Open')
        if price>intent['limit_price']:
            with store.tx() as db:db.execute("UPDATE order_intents SET status='SIMULATED_NO_FILL' WHERE intent_id=?",(intent['intent_id'],))
            continue
        if any(p['ticker']==intent['ticker'] for p in positions(store)):raise ValueError('Duplicate simulated position')
        with store.tx() as db:
            db.execute('INSERT INTO simulated_fills VALUES(?,?,?,?,?,?,?)',(intent['intent_id'],'BUY',intent['ticker'],intent['quantity'],price,day,now()))
            db.execute('INSERT INTO simulated_positions VALUES(?,?,?,?,?,?)',(intent['ticker'],intent['strategy_id'],intent['quantity'],day,intent['target_exit_date'],price))
            store._enqueue(db,'sim-open:'+intent['intent_id'],'opened',dict(test=True,ticker=intent['ticker'],price=price,
                           notional_usd=price*intent['quantity'],strategy=intent['strategy_id']))
        result['simulated_entries']+=1
    for pos in positions(store):
        if pos['exit_session']!=day:continue
        if pos['ticker'] not in bars.index:raise ValueError('Missing exit simulation bar')
        price=float(bars.loc[pos['ticker'],'Close'])
        if not math.isfinite(price) or price<=0:raise ValueError('Invalid simulated Close')
        intent=store.db.execute("SELECT * FROM order_intents WHERE ticker=? AND intended_entry_date=? AND account_id='DRY_RUN'",(pos['ticker'],pos['entry_session'])).fetchone()
        if intent is None:raise ValueError('Simulated position lacks an intent')
        with store.tx() as db:
            db.execute('INSERT INTO simulated_fills VALUES(?,?,?,?,?,?,?)',(intent['intent_id'],'SELL',pos['ticker'],pos['quantity'],price,day,now()))
            db.execute('DELETE FROM simulated_positions WHERE ticker=?',(pos['ticker'],))
            db.execute("UPDATE order_intents SET status='SIMULATED_CLOSED' WHERE intent_id=?",(intent['intent_id'],))
            store._enqueue(db,'sim-close:'+intent['intent_id'],'closed',dict(test=True,ticker=pos['ticker'],price=price,
                           session=day,pnl_usd=pos['quantity']*(price-pos['avg_entry_price']),pnl_pct=(price/pos['avg_entry_price']-1)*100))
        result['simulated_exits']+=1
    return result
