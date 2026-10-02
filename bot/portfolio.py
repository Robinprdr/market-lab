"""Account-scoped pre-order controls, separate from signal generation."""
from datetime import datetime,timezone
import hashlib
import math

from .models import OrderIntent


def intent_id(strategy_id,ticker,side,session,account,mode):
    payload='|'.join((strategy_id,ticker,side,session,account,mode))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def projected(store,snapshot,settings,ignore_intent_id=None):
    positions={ticker:abs(pos.market_value) for ticker,pos in snapshot.positions.items()}
    pending=[r for r in store.active_intents() if r['account_id']==snapshot.account_id and r['side']=='BUY'
             and r['intent_id']!=ignore_intent_id]
    reserved=sum(r['quantity']*r['limit_price'] for r in pending if r['limit_price'])
    pending_tickers={r['ticker'] for r in pending}
    return positions,pending_tickers,reserved


def entry_intent(signal,store,snapshot,settings,ignore_intent_id=None):
    positions,pending_tickers,reserved=projected(store,snapshot,settings,ignore_intent_id)
    if signal.ticker in positions or signal.ticker in pending_tickers:
        return None,'ALREADY_HELD_OR_PENDING'
    if len(set(positions)|pending_tickers)>=settings.max_positions:
        return None,'MAX_POSITIONS'
    reserved_exits=store.due_exits_on(snapshot.account_id,signal.entry_date)
    if store.orders_on(signal.entry_date,ignore_intent_id)+reserved_exits>=settings.max_orders_per_day:
        return None,'MAX_ORDERS_PER_DAY'
    if signal.reference_close<=0 or not math.isfinite(signal.reference_close):
        return None,'BAD_REFERENCE_PRICE'
    price_cap=math.floor(signal.reference_close*(1+settings.max_entry_price_drift)*100)/100
    if price_cap<=0:
        return None,'BAD_LIMIT_PRICE'
    gross_exposure=sum(positions.values())+reserved
    cap=min(settings.initial_equity_usd*settings.weight_per_entry,
            settings.initial_equity_usd*settings.max_exposure_per_ticker,
            settings.initial_equity_usd*settings.max_total_exposure-gross_exposure,
            settings.max_order_notional_usd,
            snapshot.available_cash-reserved)
    quantity=math.floor((cap-1e-6)/price_cap)
    if quantity<1:
        return None,'CASH_OR_EXPOSURE_LIMIT'
    intended=quantity*price_cap
    if gross_exposure+intended>settings.initial_equity_usd*settings.max_total_exposure+1e-8:
        return None,'MAX_TOTAL_EXPOSURE'
    account=settings.allowed_account_id if settings.trading_mode=='PAPER' else 'DRY_RUN'
    intent=OrderIntent(intent_id(signal.strategy_id,signal.ticker,'BUY',signal.entry_date,account,settings.trading_mode),
        signal.strategy_id,signal.ticker,'BUY',quantity,signal.entry_date,signal.reason,
        datetime.now(timezone.utc).isoformat(),signal.holding_sessions,signal.exit_date,
        'LOO',price_cap,account,signal.reference_close)
    return intent,None


def exit_intent(position,store,snapshot,settings,ignore_intent_id=None):
    ticker=position['ticker'];session=position['exit_session']
    if ticker not in snapshot.positions or snapshot.positions[ticker].quantity != position['quantity']:
        return None,'RECONCILIATION_REQUIRED'
    if store.orders_on(session,ignore_intent_id)>=settings.max_orders_per_day:
        return None,'MAX_ORDERS_PER_DAY'
    account=settings.allowed_account_id if settings.trading_mode=='PAPER' else 'DRY_RUN'
    intent=OrderIntent(intent_id(position['strategy_id'],ticker,'SELL',session,account,settings.trading_mode),
        position['strategy_id'],ticker,'SELL',position['quantity'],session,
        'Frozen V2 exit at close of ninth market session',datetime.now(timezone.utc).isoformat(),
        9,session,'MOC',None,account,position['avg_entry_price'])
    return intent,None
