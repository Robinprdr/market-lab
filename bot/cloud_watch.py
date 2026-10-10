"""Independent health timer; it never instantiates a broker."""
from datetime import datetime, timezone
import json
import os
import socket

from .calendar import exchange
from .cloud import record_health
import pandas as pd

from .cloud import cloud_settings, health
from .simulation import initialize
from .storage import Store


def gateway_status(enabled=False):
    if not enabled:return dict(state='NOT_REQUIRED_FOR_DRY_RUN',api_authenticated=False)
    try:
        with socket.create_connection(('127.0.0.1',4002),timeout=1):pass
        return dict(state='SOCKET_REACHABLE_ONLY',api_authenticated=False)
    except OSError:return dict(state='SOCKET_UNREACHABLE',api_authenticated=False)


def inspect(store,min_free=1024**3,at=None):
    at=at or datetime.now(timezone.utc)
    status=health(store);issues=[]
    heartbeat=status['checks'].get('scheduler_heartbeat')
    if not heartbeat or (at-datetime.fromisoformat(heartbeat['observed_at'])).total_seconds()>300:issues.append('SCHEDULER_STALE')
    if status['disk_free_bytes']<min_free:issues.append('DISK_LOW')
    state=store.operations_state()
    if state and state['state'] in ('ERROR','DATA_ERROR','RECONCILIATION_REQUIRED'):issues.append(state['state'])
    gateway=gateway_status(os.getenv('IBKR_GATEWAY_MONITOR','false').lower()=='true')
    record_health(store,'gateway',gateway)
    if gateway['state']=='SOCKET_UNREACHABLE':issues.append('GATEWAY_UNREACHABLE')
    if gateway['state']=='SOCKET_REACHABLE_ONLY':record_health(store,'last_gateway_socket_success',dict(scope='TCP_ONLY_NOT_BROKER_AUTHENTICATION'))
    day=at.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
    schedule=exchange(day).schedule
    if pd.Timestamp(day) in schedule.index and pd.Timestamp(at)>schedule.loc[pd.Timestamp(day),'close']+pd.Timedelta(hours=2):
        data=status['checks'].get('daily_data',{}).get('value',{})
        if data.get('session')!=day:issues.append('DATA_STALE')
    for issue in issues:
        with store.tx() as db:store._enqueue(db,'health:'+issue+':'+at.date().isoformat(),'critical_error',dict(test=True,code=issue,message='DRY_RUN deployment needs inspection'))
    return dict(issues=issues,broker=status['broker'],gateway=gateway,orders_sent=0)


def main():
    cfg=cloud_settings();store=Store(cfg.db_path)
    try:initialize(store,cfg);print(json.dumps(inspect(store)))
    finally:store.close()


if __name__=='__main__':main()
