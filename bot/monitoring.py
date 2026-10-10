"""Read-only projections of the Bot Core SQLite ledger for status and web UI."""
import json
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo

from .operations import upcoming


def dashboard_data(store,settings):
    db=store.db
    last=db.execute('SELECT * FROM daily_runs ORDER BY started_at DESC LIMIT 1').fetchone()
    last_reconcile=db.execute("SELECT * FROM daily_runs WHERE kind='reconcile' ORDER BY started_at DESC LIMIT 1").fetchone()
    state=store.operations_state()
    enabled=store.dry_run_enabled() if settings.trading_mode=='DRY_RUN' else False
    today=datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    signals=[dict(row) for row in db.execute('SELECT * FROM signals ORDER BY signal_date DESC,ticker LIMIT 50')]
    orders=[dict(row) for row in db.execute('''SELECT i.intent_id,i.strategy_id,i.ticker,i.side,i.quantity,
        i.intended_entry_date,i.target_exit_date,i.status,i.reason,i.refusal_reason,
        o.broker_order_id,o.filled_qty,o.status AS broker_status FROM order_intents i
        LEFT JOIN orders o USING(intent_id) ORDER BY i.created_at DESC LIMIT 100''')]
    errors=[dict(row) for row in db.execute('SELECT * FROM errors ORDER BY error_id DESC LIMIT 50')]
    positions=[dict(row) for row in db.execute('SELECT * FROM positions ORDER BY ticker')]
    executions=[dict(row) for row in db.execute('SELECT * FROM executions ORDER BY session DESC,received_at DESC LIMIT 200')]
    simulated=[];deployment={}
    if settings.trading_mode=='DRY_RUN' and db.execute("SELECT 1 FROM sqlite_master WHERE name='simulated_positions'").fetchone():
        simulated=[dict(row) for row in db.execute('SELECT * FROM simulated_positions ORDER BY ticker')]
        from .cloud import health
        deployment=health(store)
    decisions=[]
    for row in db.execute("SELECT asof,summary_json FROM daily_runs WHERE kind='daily' ORDER BY started_at DESC LIMIT 20"):
        summary=json.loads(row['summary_json'] or '{}')
        decisions.extend(dict(item,asof=row['asof']) for item in summary.get('decisions',[]))
    pending_entries=[item for item in orders if item['side']=='BUY' and
                     (item['status'] in ('PLANNED','SUBMITTING','SENT','ACKNOWLEDGED','PARTIAL') or
                      item['status']=='DRY_RUN' and item['intended_entry_date']>=today)]
    pending_exits=[item for item in orders if item['side']=='SELL' and item['status'] in
                   ('PLANNED','SUBMITTING','SENT','ACKNOWLEDGED','PARTIAL')]
    trades=[]
    by_ticker={}
    for fill in reversed(executions):
        ticker=fill['ticker']
        position=by_ticker.setdefault(ticker,dict(quantity=0,cost=0.,strategy=None,entry=None))
        if fill['side']=='BUY':
            position['quantity']+=fill['quantity'];position['cost']+=fill['quantity']*fill['price']
            position['entry']=position['entry'] or fill['session']
            source=db.execute('SELECT strategy_id FROM order_intents WHERE intent_id=?',(fill['intent_id'],)).fetchone()
            position['strategy']=source['strategy_id'] if source else None
        elif position['quantity']>=fill['quantity']:
            avg=position['cost']/position['quantity']
            pnl=fill['quantity']*(fill['price']-avg)
            duration=(date.fromisoformat(fill['session'])-date.fromisoformat(position['entry'])).days
            trades.append(dict(ticker=ticker,strategy=position['strategy'],entry=position['entry'],
                               exit=fill['session'],quantity=fill['quantity'],pnl_usd=pnl,
                               duration_days=duration))
            position['quantity']-=fill['quantity'];position['cost']-=fill['quantity']*avg
            if not position['quantity']:position.update(cost=0.,entry=None)
    next_runs=upcoming(limit=4)
    bot_state=state['state'] if state else 'DISABLED'
    heartbeat=deployment.get('checks',{}).get('scheduler_heartbeat',{})
    activity=heartbeat.get('observed_at') or (state['updated_at'] if state else None)
    if enabled and activity and (datetime.now(timezone.utc)-datetime.fromisoformat(activity)).total_seconds()>300:
        bot_state='ERROR'
    reconciliation=(f"{last_reconcile['mode']}:{last_reconcile['status']} @ {last_reconcile['started_at']}"
                    if last_reconcile else 'NOT_RUN')
    return dict(state=bot_state,state_record=state,kill_switch_enabled=store.kill_switch_enabled(),
                mode=settings.trading_mode,trading_enabled=settings.trading_enabled,local_dry_run_enabled=enabled,
                broker='NOT_CONNECTED' if settings.trading_mode=='DRY_RUN' else 'NOT_PROBED',
                broker_connected=False,account=settings.allowed_account_id or None,
                reconciliation=reconciliation,
                cash_usd=None,net_liquidation=None,exposure_usd=None,pnl_usd=sum(t['pnl_usd'] for t in trades) if trades else None,
                positions=positions,position_count=len(positions),signals=signals,
                simulated_positions=simulated,deployment_health=deployment,
                decisions=decisions[:100],orders=orders,trades=list(reversed(trades)),errors=errors,
                pending_entries=pending_entries,pending_exits=pending_exits,
                last_run=dict(last) if last else None,next_runs=next_runs,
                executions=executions[:50])
