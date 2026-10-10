"""Local NYSE-aware DRY_RUN scheduler. Never creates an IBKR adapter."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import time

import pandas as pd

from .calendar import exchange, last_complete_session
from .config import from_env
from .market_data import YahooDailyProvider
from .runtime import run_daily
from .storage import Store
from .strategy import FrozenSwingV2

JOBS=('reconcile','preopen','exits','data_refresh','daily')


def session_schedule(day,row=None):
    """All returned instants are timezone-aware UTC; half days use their actual close."""
    if row is None:row=exchange(day).schedule.loc[pd.Timestamp(day)]
    opening=row['open'].to_pydatetime()
    closing=row['close'].to_pydatetime()
    return {'reconcile':opening-timedelta(minutes=120),
            'preopen':opening-timedelta(minutes=15),
            'exits':closing-timedelta(minutes=90),
            'data_refresh':closing+timedelta(minutes=30),
            'daily':closing+timedelta(minutes=45)}


def upcoming(now=None,limit=4):
    now=pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert('UTC')
    calendar=exchange(now.tz_convert('America/New_York').date())
    events=[]
    for day,row in calendar.schedule.iterrows():
        for name,when in session_schedule(day,row).items():
            if pd.Timestamp(when)>now:
                events.append(dict(job=name,session=day.date().isoformat(),at_utc=when.isoformat(),
                                   at_et=pd.Timestamp(when).tz_convert('America/New_York').isoformat()))
    return sorted(events,key=lambda item:item['at_utc'])[:limit]


def due_jobs(now=None):
    now=pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert('UTC')
    calendar=exchange(now.tz_convert('America/New_York').date())
    due=[]
    # Only the present session and its immediate predecessor; never replay old orders.
    for day,row in calendar.schedule.iterrows():
        if abs((day.date()-now.date()).days)>4:continue
        for name,when in session_schedule(day,row).items():
            when=pd.Timestamp(when)
            deadline=when+pd.Timedelta(minutes=10) if name=='preopen' else when+pd.Timedelta(hours=2)
            if when<=now<deadline:
                due.append((name,day.date().isoformat()))
    return due


def _completed(store,kind,day):
    return store.db.execute("SELECT 1 FROM daily_runs WHERE kind=? AND asof=? AND status='OK' LIMIT 1",
                            (kind,day)).fetchone() is not None


def _logged_job(store,kind,day,work):
    run=store.run_start(kind,'DRY_RUN',day)
    try:
        summary=work()
        store.run_end(run,'OK',summary)
        return summary
    except Exception as exc:
        store.error(run,'DATA_ERROR' if kind=='data_refresh' else 'ERROR',str(exc))
        store.run_end(run,'FAILED',dict(error=str(exc)))
        raise


def _local_reconcile(store):
    """DRY_RUN consistency check; it makes no broker connection or paper claim."""
    count=store.db.execute("SELECT COUNT(*) FROM orders WHERE account_id='DRY_RUN'").fetchone()[0]
    if count:
        raise RuntimeError('RECONCILIATION_REQUIRED: DRY_RUN contains broker orders')
    return dict(broker='NOT_CONNECTED',dry_run_intents=store.db.execute(
        "SELECT COUNT(*) FROM order_intents WHERE status='DRY_RUN'").fetchone()[0])


def _dry_exits(store,day):
    rows=store.db.execute("""SELECT ticker,intent_id FROM order_intents
        WHERE status='DRY_RUN' AND side='BUY' AND target_exit_date=?""",(day,)).fetchall()
    return dict(scheduled_exits=[dict(row) for row in rows],orders_sent=0)


def _dry_preopen(store,day):
    plans=store.db.execute("SELECT intent_id,ticker FROM order_intents WHERE status='DRY_RUN' AND side='BUY' AND intended_entry_date=?",(day,)).fetchall()
    return dict(prepared_entries=[dict(row) for row in plans],orders_sent=0,
                broker='DISABLED_BY_DRY_RUN_POLICY',deadline_et='09:25')


def tick(store,settings,provider=None,strategy=None,now=None):
    if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
        raise ValueError('Operations V1 is DRY_RUN only; PAPER and orders are blocked')
    if not store.dry_run_enabled():
        store.set_operations_state('DISABLED')
        return []
    provider=provider or YahooDailyProvider()
    strategy=strategy or FrozenSwingV2()
    results=[]
    for kind,day in due_jobs(now):
        if _completed(store,kind,day):continue
        store.set_operations_state('RUNNING')
        try:
            if kind=='reconcile':
                result=_logged_job(store,kind,day,lambda:_local_reconcile(store))
            elif kind=='preopen':
                result=_logged_job(store,kind,day,lambda:_dry_preopen(store,day))
            elif kind=='exits':
                result=_logged_job(store,kind,day,lambda:_dry_exits(store,day))
            elif kind=='data_refresh':
                result=_logged_job(store,kind,day,lambda:dict(rows=len(provider.load(day))))
            else:
                result=run_daily(store,settings,strategy,provider,asof=day,at_utc=now)
            store.set_operations_state('READY',last_execution=datetime.now(timezone.utc).isoformat())
            results.append(dict(job=kind,session=day,result=result))
        except Exception as exc:
            state=('DATA_ERROR' if kind in ('daily','data_refresh') else
                   'RECONCILIATION_REQUIRED' if kind=='reconcile' else 'ERROR')
            store.set_operations_state(state,last_error=str(exc))
            results.append(dict(job=kind,session=day,error=str(exc)))
            # Never proceed to another scheduled job after failure.
            break
    if not results:
        prior=store.operations_state()
        if prior is None or prior['state'] in ('READY','RUNNING'):
            store.set_operations_state('READY')
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true',help='Perform one scheduler evaluation and exit')
    parser.add_argument('--interval',type=int,default=60,help='Poll interval in seconds (>=15)')
    args=parser.parse_args()
    if args.interval<15:parser.error('--interval must be at least 15 seconds')
    settings=from_env()
    if settings.trading_mode!='DRY_RUN' or settings.trading_enabled:
        parser.error('Set TRADING_MODE=DRY_RUN and TRADING_ENABLED=false')
    store=Store(settings.db_path)
    try:
        while True:
            print(json.dumps(tick(store,settings),default=str),flush=True)
            if args.once:break
            time.sleep(args.interval)
    finally:
        store.close()


if __name__=='__main__':main()
