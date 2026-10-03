"""Causal daily orchestration, broker synchronization and fail-closed execution."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import math

from .calendar import before_moc_cutoff,before_next_open,last_complete_session
from .models import BrokerSnapshot,OrderIntent
from .portfolio import entry_intent,exit_intent,intent_id


class ReconciliationRequired(RuntimeError):
    pass


def synchronize(store,broker,account):
    """Broker is truth. Only known execution IDs may change local position state."""
    snapshot=broker.snapshot(account)
    if snapshot.account_id!=account:
        raise ReconciliationRequired('RECONCILIATION_REQUIRED: wrong broker account')
    if not math.isfinite(snapshot.available_cash) or snapshot.available_cash<0:
        raise ReconciliationRequired('RECONCILIATION_REQUIRED: invalid account cash')
    if any(p.quantity<=0 or not math.isfinite(p.market_value) or p.market_value<0 for p in snapshot.positions.values()):
        raise ReconciliationRequired('RECONCILIATION_REQUIRED: unsupported broker position')
    try:
        for order in snapshot.open_orders:
            if order.account_id != account:
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: wrong-account order')
            store.bind_open_order(order)
        for execution in snapshot.executions:
            if execution.account_id!=account:
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: wrong-account execution')
            store.sync_execution(execution)
    except RuntimeError as exc:
        raise ReconciliationRequired(str(exc)) from exc
    local=store.positions(account)
    broker_positions={t:p.quantity for t,p in snapshot.positions.items() if p.quantity}
    local_positions={t:int(p['quantity']) for t,p in local.items() if p['quantity']}
    if local_positions!=broker_positions:
        raise ReconciliationRequired(f'RECONCILIATION_REQUIRED: positions DB {local_positions} vs broker {broker_positions}')
    open_ids={o.intent_id for o in snapshot.open_orders}
    for row in store.active_intents():
        if row['account_id']!=account:
            continue
        if row['status']=='SUBMITTING':
            raise ReconciliationRequired('RECONCILIATION_REQUIRED: ambiguous submission '+row['intent_id'])
        if row['status'] in ('SENT','ACKNOWLEDGED','PARTIAL') and row['intent_id'] not in open_ids:
            raise ReconciliationRequired('RECONCILIATION_REQUIRED: order absent from open-order snapshot '+row['intent_id'])
    return snapshot


def _submit(store,broker,intent,settings):
    if not settings.trading_enabled:
        raise ValueError('KILL_SWITCH')
    if settings.trading_mode!='PAPER' or intent.account_id!=settings.allowed_account_id:
        raise ValueError('ACCOUNT_OR_MODE_REJECTED')
    with store.order_gate():
        if store.kill_switch_enabled():
            raise ValueError('KILL_SWITCH')
        if not store.order_claim(intent.intent_id,settings.allowed_account_id):
            raise ReconciliationRequired('RECONCILIATION_REQUIRED: duplicate or non-planned intent')
        # DB now says SUBMITTING. Any timeout/crash remains ambiguous; never retry blind.
        broker_id=broker.submit(intent)
        store.order_ack(intent.intent_id,broker_id)
        return broker_id


def run_daily(store,settings,strategy,provider,broker=None,asof=None,at_utc=None):
    day=asof or last_complete_session(at_utc)
    run_id=store.run_start('daily',settings.trading_mode,day)
    summary=dict(asof=day,market_data_updated=False,signals=0,accepted=0,refused=0,
                 reasons={},orders_sent=0,orders_executed=0,positions=0,decisions=[])
    try:
        if settings.trading_mode=='PAPER' and day!=last_complete_session(at_utc):
            raise ValueError('PAPER requires most recent completed session')
        if settings.trading_mode=='PAPER' and settings.trading_enabled and not before_next_open(day,at_utc):
            raise ValueError('Entry deadline missed; no late order')
        frame=provider.load(day);summary['market_data_updated']=True
        signals=strategy.generate_signals(frame,day)
        store.register(strategy.strategy_id,'results/research_v2/frozen_candidates.json')
        summary['signals']=len(signals)
        for signal in signals:store.save_signal(signal)
        if settings.trading_mode=='PAPER' and settings.trading_enabled:
            if broker is None:raise RuntimeError('PAPER enabled requires an IBKR broker')
            snapshot=synchronize(store,broker,settings.allowed_account_id)
            if hasattr(provider,'unadjusted_bar_price'):
                for fill in store.missing_benchmarks(day):
                    price=provider.unadjusted_bar_price(fill['ticker'],fill['session'],day,fill['side'])
                    if price is not None:store.record_benchmark(fill['execution_id'],price,
                                                                  'OPEN' if fill['side']=='BUY' else 'CLOSE')
            today=last_complete_session(at_utc)
            if any(p['exit_session']<=today for p in store.positions(settings.allowed_account_id).values()):
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: overdue exit; no new entry')
            summary['positions']=len(snapshot.positions)
        elif settings.trading_mode=='DRY_RUN':
            snapshot=BrokerSnapshot('DRY_RUN',settings.initial_equity_usd)
        else:
            snapshot=None
        for signal in sorted(signals,key=lambda s:s.ticker):
            if snapshot is None:
                reason='KILL_SWITCH'
                summary['refused']+=1;summary['reasons'][reason]=summary['reasons'].get(reason,0)+1
                summary['decisions'].append(dict(ticker=signal.ticker,accepted=False,reason=reason))
                continue
            account=settings.allowed_account_id if settings.trading_mode=='PAPER' else 'DRY_RUN'
            existing_id=intent_id(signal.strategy_id,signal.ticker,'BUY',signal.entry_date,account,settings.trading_mode)
            existing=store.intent(existing_id)
            if existing is not None and existing['status']=='PLANNED' and settings.trading_mode=='PAPER':
                checked,reason=entry_intent(signal,store,snapshot,settings,ignore_intent_id=existing_id)
                if reason or checked.quantity<existing['quantity'] or checked.limit_price<existing['limit_price'] or existing['target_exit_date']!=signal.exit_date:
                    raise ReconciliationRequired('RECONCILIATION_REQUIRED: planned intent no longer passes risk check')
                intent=OrderIntent(existing['intent_id'],existing['strategy_id'],existing['ticker'],existing['side'],
                    existing['quantity'],existing['intended_entry_date'],existing['reason'],existing['created_at'],
                    existing['holding_sessions'],existing['target_exit_date'],existing['order_type'],existing['limit_price'],
                    existing['account_id'],existing['reference_close'])
            else:
                intent,reason=entry_intent(signal,store,snapshot,settings)
            if reason:
                summary['refused']+=1;summary['reasons'][reason]=summary['reasons'].get(reason,0)+1
                summary['decisions'].append(dict(ticker=signal.ticker,accepted=False,reason=reason))
                continue
            if settings.trading_mode=='DRY_RUN':
                store.save_intent(intent,'DRY_RUN')
            else:
                previous=store.save_intent(intent,'PLANNED')
                if previous['status']!='PLANNED':
                    reason='DUPLICATE_INTENT'
                    summary['refused']+=1;summary['reasons'][reason]=summary['reasons'].get(reason,0)+1
                    summary['decisions'].append(dict(ticker=signal.ticker,accepted=False,reason=reason))
                    continue
                _submit(store,broker,intent,settings)
                summary['orders_sent']+=1
            summary['accepted']+=1
            summary['decisions'].append(dict(ticker=signal.ticker,accepted=True,intent_id=intent.intent_id,
                                            side=intent.side,quantity=intent.quantity,limit_price=intent.limit_price,
                                            intended_entry_date=intent.intended_entry_date,exit_date=intent.target_exit_date))
        summary['orders_executed']=store.executions_since_run(run_id)
        store.run_end(run_id,'OK',summary)
        return summary
    except Exception as exc:
        store.error(run_id,'RECONCILIATION_REQUIRED' if isinstance(exc,ReconciliationRequired) else 'RUN_FAILED',str(exc))
        store.run_end(run_id,'FAILED',summary)
        raise


def run_exits(store,settings,broker=None,today=None,at_utc=None):
    day=today or datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    run_id=store.run_start('exits',settings.trading_mode,day)
    summary=dict(day=day,orders_sent=0,refused=0,decisions=[])
    try:
        if settings.trading_mode!='PAPER' or not settings.trading_enabled:
            summary['reason']='KILL_SWITCH_OR_DRY_RUN';store.run_end(run_id,'OK',summary);return summary
        if not before_moc_cutoff(day,at_utc):
            raise ValueError('MOC submission window closed or market not open')
        if broker is None:raise RuntimeError('PAPER exits require IBKR broker')
        snapshot=synchronize(store,broker,settings.allowed_account_id)
        positions=store.positions(settings.allowed_account_id)
        if any(p['exit_session']<day for p in positions.values()):
            raise ReconciliationRequired('RECONCILIATION_REQUIRED: overdue position')
        for ticker,pos in sorted(positions.items()):
            if pos['exit_session']!=day:continue
            existing_id=intent_id(pos['strategy_id'],ticker,'SELL',day,settings.allowed_account_id,settings.trading_mode)
            existing=store.intent(existing_id)
            if existing is not None and existing['status'] in ('SENT','ACKNOWLEDGED','PARTIAL'):
                summary['decisions'].append(dict(ticker=ticker,reason='ALREADY_SUBMITTED'))
                continue
            ignore_id=existing_id if existing is not None and existing['status']=='PLANNED' else None
            intent,reason=exit_intent(pos,store,snapshot,settings,ignore_id)
            if reason:
                summary['refused']+=1;summary['decisions'].append(dict(ticker=ticker,reason=reason))
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: due exit refused: '+reason)
            if existing is not None and (existing['status']!='PLANNED' or existing['quantity']!=intent.quantity):
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: due exit plan changed')
            previous=store.save_intent(intent,'PLANNED')
            if previous['status']!='PLANNED':
                if previous['status'] in ('SENT','ACKNOWLEDGED','PARTIAL'):
                    summary['decisions'].append(dict(ticker=ticker,reason='ALREADY_SUBMITTED'))
                    continue
                raise ReconciliationRequired('RECONCILIATION_REQUIRED: due exit has unexpected intent status')
            _submit(store,broker,intent,settings);summary['orders_sent']+=1
            summary['decisions'].append(dict(ticker=ticker,intent_id=intent.intent_id,quantity=intent.quantity))
        store.run_end(run_id,'OK',summary);return summary
    except Exception as exc:
        store.error(run_id,'RECONCILIATION_REQUIRED' if isinstance(exc,ReconciliationRequired) else 'RUN_FAILED',str(exc))
        store.run_end(run_id,'FAILED',summary);raise


def run_reconcile(store,settings,broker):
    run_id=store.run_start('reconcile',settings.trading_mode)
    try:
        if settings.trading_mode!='PAPER':
            raise ValueError('Broker reconciliation requires PAPER mode')
        snapshot=synchronize(store,broker,settings.allowed_account_id)
        result=dict(account_id=snapshot.account_id,available_cash_usd=snapshot.available_cash,
                    account_currency=snapshot.account_currency,total_cash=snapshot.total_cash,
                    net_liquidation=snapshot.net_liquidation,
                    positions={t:p.quantity for t,p in snapshot.positions.items()},
                    open_orders=len(snapshot.open_orders),executions_seen=len(snapshot.executions))
        store.run_end(run_id,'OK',result);return result
    except Exception as exc:
        store.error(run_id,'RECONCILIATION_REQUIRED',str(exc));store.run_end(run_id,'FAILED');raise
