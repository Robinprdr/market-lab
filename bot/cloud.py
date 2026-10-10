"""Linux deployment scheduler: DRY_RUN only, with no broker adapter."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from .config import Settings, from_env
from .calendar import last_complete_session
from .market_data import YahooDailyProvider
from .operations import due_jobs, _completed, _local_reconcile, _dry_preopen, _dry_exits
from .simulation import initialize, plan, settle, positions, reconcile
from .storage import Store, now
from .strategy import FrozenSwingV2


def cloud_settings():
    cfg=from_env()
    if cfg.trading_mode!='DRY_RUN' or cfg.trading_enabled:
        raise ValueError('Cloud V1 requires DRY_RUN and trading disabled')
    if cfg.allowed_account_id and cfg.allowed_account_id!='DUR231204':
        raise ValueError('Unauthorized account configuration')
    if not os.getenv('BOT_DB_PATH') or cfg.db_path.resolve()==Settings.db_path.resolve():
        raise ValueError('Explicit isolated BOT_DB_PATH required')
    return cfg


@contextmanager
def scheduler_lease(path):
    lock=Path(str(path)+'.scheduler.lock').open('a')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Scheduler already running') from None
        yield
    finally:lock.close()


def record_health(store,key,value):
    with store.tx() as db:
        db.execute('INSERT OR REPLACE INTO deployment_health VALUES(?,?,?)',(key,json.dumps(value),now()))


def health(store):
    values={r['key']:dict(value=json.loads(r['value']),observed_at=r['observed_at'])
            for r in store.db.execute('SELECT * FROM deployment_health')}
    return dict(checks=values,disk_free_bytes=shutil.disk_usage(store.path.parent).free,
                broker='DISABLED_BY_DRY_RUN_POLICY',kill_switch=store.kill_switch_enabled(),
                simulated_positions=len(positions(store)),
                recent_jobs=[dict(r) for r in store.db.execute('SELECT kind,asof,status,started_at,ended_at FROM daily_runs ORDER BY started_at DESC LIMIT 10')])


def tick(store,settings,provider=None,strategy=None,at=None):
    initialize(store,settings)
    record_health(store,'scheduler_heartbeat',dict(pid=os.getpid()))
    if not store.dry_run_enabled() or store.kill_switch_enabled():
        store.set_operations_state('DISABLED');return []
    provider=provider or YahooDailyProvider(cache=store.path.parent/'daily-data')
    strategy=strategy or FrozenSwingV2()
    results=[]
    for kind,day in due_jobs(at):
        if _completed(store,kind,day):continue
        failures=store.db.execute("SELECT COUNT(*) FROM daily_runs WHERE kind=? AND asof=? AND status='FAILED'",(kind,day)).fetchone()[0]
        if failures>=3:
            store.set_operations_state('ERROR',last_error='Job retry limit; operator required');break
        if kind=='daily' and not _completed(store,'data_refresh',day):
            store.set_operations_state('DATA_ERROR',last_error='Missing successful data refresh');break
        if kind=='preopen' and not _completed(store,'daily',last_complete_session(at)):
            store.set_operations_state('DATA_ERROR',last_error='Missing preceding session plan');break
        store.set_operations_state('RUNNING')
        try:
            run=store.run_start(kind,'DRY_RUN',day)
            try:
                if kind=='reconcile':result=reconcile(store,settings)
                elif kind=='preopen':result=_dry_preopen(store,day)
                elif kind=='exits':result=_dry_exits(store,day)
                else:
                    frame=provider.load(day)
                    if kind=='data_refresh':
                        result=settle(store,settings,frame,day,at)
                        result['rows']=len(frame)
                        record_health(store,'daily_data',dict(session=day,rows=len(frame)))
                    else:result=plan(store,settings,strategy,frame,day)
                store.run_end(run,'OK',result)
            except Exception:
                # Do not persist network URLs or exception text which may contain credentials.
                store.error(run,'DATA_ERROR' if kind in ('daily','data_refresh') else 'RUN_FAILED','Cloud job failed; no broker action')
                store.run_end(run,'FAILED',dict(error='JOB_FAILED'));raise
            store.set_operations_state('READY',last_execution=now())
            record_health(store,'last_job',dict(job=kind,session=day,status='OK'))
            results.append(dict(job=kind,session=day,result=result))
        except Exception:
            store.set_operations_state('DATA_ERROR' if kind in ('daily','data_refresh') else 'RECONCILIATION_REQUIRED',last_error='JOB_FAILED')
            results.append(dict(job=kind,session=day,error='JOB_FAILED'));break
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--health',action='store_true')
    parser.add_argument('--interval',type=int,default=60)
    args=parser.parse_args()
    if args.interval<15:parser.error('--interval must be >=15')
    cfg=cloud_settings();store=Store(cfg.db_path)
    try:
        initialize(store,cfg)
        if args.health:print(json.dumps(health(store)));return
        with scheduler_lease(store.path):
            record_health(store,'scheduler_start',dict(pid=os.getpid()))
            while True:
                print(json.dumps(tick(store,cfg),default=str),flush=True)
                if args.once:break
                time.sleep(args.interval)
    finally:store.close()


if __name__=='__main__':main()
