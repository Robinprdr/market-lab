"""Multi-session operational replay: frozen rules, offline data, no broker/network API."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from .backup import copy_database
from .calendar import exchange, exit_session
from .cloud import tick
from .config import Settings
from .simulation import initialize, positions, reconcile
from .storage import Store
from .strategy import FrozenSwingV2
from .telegram.client import TelegramWorker
from .telegram.__main__ import poll_once
from .web import create_app


class OfflineData:
    def __init__(self,panel):self.panel=panel;self.fail_once=False
    def load(self,day):
        if self.fail_once:
            self.fail_once=False;raise RuntimeError('Controlled offline data incident')
        return self.panel[self.panel.Date.le(pd.Timestamp(day))].copy()


class OfflineTelegram:
    def __init__(self):self.sent=[];self.updates=[];self.fail_once=False
    def get_updates(self,offset):return [u for u in self.updates if u['update_id']>=offset]
    def send_message(self,user,text):
        if self.fail_once:self.fail_once=False;raise RuntimeError('Controlled delivery incident')
        self.sent.append(text)
    def command(self,text):
        self.updates.append(dict(update_id=len(self.updates)+1,message={
            'from':{'id':123456},'chat':{'id':123456,'type':'private'},'text':text}))


def replay(panel,start,end,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'audit.sqlite'
    if path.exists():raise ValueError('Audit requires a NEW isolated database')
    cfg=Settings(trading_mode='DRY_RUN',db_path=path)
    store=Store(path);initialize(store,cfg);store.set_dry_run_enabled(True)
    strategy=FrozenSwingV2();provider=OfflineData(panel);api=OfflineTelegram()
    sessions=exchange(start).schedule.loc[start:end]
    if len(sessions)<12:raise ValueError('At least 12 sessions required for operational replay')
    observations=[];incidents=[];restarts=0
    try:
        with patch('bot.broker_ibkr.IBKRPaperBroker',side_effect=AssertionError('Broker access forbidden')):
            for index,(stamp,row) in enumerate(sessions.iterrows()):
                day=stamp.date().isoformat();opening=row['open'];closing=row['close']
                if index:
                    tick(store,cfg,provider,strategy,opening+pd.Timedelta(minutes=-10))
                # Corrupt only a TEST projection, then repair from its recorded fill.
                if index==4 and positions(store):
                    pos=positions(store)[0]
                    store.db.execute('UPDATE simulated_positions SET avg_entry_price=? WHERE ticker=?',(pos['avg_entry_price']+1,pos['ticker']));store.db.commit()
                    blocked=tick(store,cfg,provider,strategy,closing-pd.Timedelta(minutes=90))
                    assert blocked[-1].get('error')=='JOB_FAILED'
                    assert store.operations_state()['state']=='RECONCILIATION_REQUIRED'
                    verified=store.db.execute("SELECT price FROM simulated_fills WHERE ticker=? AND session=? AND side='BUY'",(pos['ticker'],pos['entry_session'])).fetchone()['price']
                    store.db.execute('UPDATE simulated_positions SET avg_entry_price=? WHERE ticker=?',(verified,pos['ticker']));store.db.commit()
                    incidents.append(dict(type='SIMULATED_PROJECTION_CORRUPTION',session=day,recovery='FROM_EXISTING_SIMULATED_FILL'))
                tick(store,cfg,provider,strategy,closing-pd.Timedelta(minutes=89))
                at=closing+pd.Timedelta(minutes=60)
                if index==2:provider.fail_once=True
                if index==3:
                    # Crash after fills committed, before job completion recorded.
                    original=store.run_end
                    def crash(run,status,summary=None):
                        kind=store.db.execute('SELECT kind FROM daily_runs WHERE run_id=?',(run,)).fetchone()['kind']
                        if kind=='data_refresh' and status=='OK':raise SystemExit('CONTROLLED_CRASH')
                        return original(run,status,summary)
                    store.run_end=crash
                    try:tick(store,cfg,provider,strategy,at)
                    except SystemExit:pass
                    else:raise AssertionError('Controlled crash did not occur')
                    incidents.append(dict(type='CRASH_AFTER_COMMIT_BEFORE_JOB_ACK',session=day))
                    store.close();store=Store(path);restarts+=1
                first=tick(store,cfg,provider,strategy,at)
                if index==2:
                    assert first[0]['error']=='JOB_FAILED'
                    assert not store.db.execute("SELECT 1 FROM daily_runs WHERE kind='daily' AND asof=? AND status='OK'",(day,)).fetchone()
                    incidents.append(dict(type='DATA_FAILURE',session=day,recovery='RETRY_WITHIN_SAME_WINDOW'))
                    store.close();store=Store(path);restarts+=1
                    tick(store,cfg,provider,strategy,at+pd.Timedelta(minutes=5))
                before=store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]
                assert tick(store,cfg,provider,strategy,at+pd.Timedelta(minutes=10))==[]
                assert store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]==before
                if index==5:
                    with store.tx() as db:store._enqueue(db,'audit-invalid-notification','opened',{})
                    api.command('/status');api.command('/positions');api.fail_once=True
                    incidents.append(dict(type='TELEGRAM_INVALID_PAYLOAD_AND_DELIVERY_FAILURE',session=day))
                worker=TelegramWorker(store,cfg,api,123456)
                poll_once(worker)
                poll_once(worker)
                view=create_app(cfg).test_client().get('/api/state').json
                assert len(view['simulated_positions'])==len(positions(store))
                assert view['positions']==[] and view['trading_enabled'] is False
                assert reconcile(store,cfg)['status']=='PASS'
                observations.append(dict(session=day,state=store.operations_state()['state'],
                    simulated_positions=len(positions(store)),simulated_fills=before,orders_sent=0))
                # Close/reopen the actual ledger on every session boundary.
                store.close();store=Store(path);restarts+=1
            for intent in store.db.execute('SELECT * FROM order_intents'):
                assert intent['target_exit_date']==exit_session(intent['intended_entry_date'],9)
            for table in ('orders','executions','positions'):
                assert store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
            counts={r['status']:r['n'] for r in store.db.execute('SELECT status,COUNT(*) n FROM order_intents GROUP BY status')}
            for kind in ('daily','data_refresh','preopen','exits','reconcile'):
                assert not store.db.execute("SELECT 1 FROM daily_runs WHERE kind=? AND status='OK' GROUP BY asof HAVING COUNT(*)>1",(kind,)).fetchone()
            backup=copy_database(path,directory/'backup.sqlite');restored=copy_database(backup,directory/'restored.sqlite')
            recovered=Store(restored)
            try:assert reconcile(recovered,Settings(trading_mode='DRY_RUN',db_path=restored))['status']=='PASS'
            finally:recovered.close()
            held=len(positions(store));fills=store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]
            api.command('/kill');poll_once(TelegramWorker(store,cfg,api,123456))
            assert store.kill_switch_enabled() and len(positions(store))==held
            assert tick(store,cfg,provider,strategy,sessions.iloc[-1]['close']+pd.Timedelta(minutes=80))==[]
            assert store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]==fills
            store.close();store=Store(path);restarts+=1
            assert store.kill_switch_enabled()
            return dict(status='PASS',scope='OFFLINE_OPERATIONAL_SIMULATION_NOT_PERFORMANCE_BACKTEST',
                        frozen_candidate=strategy.strategy_id,start=start,end=end,sessions=len(observations),
                        restarts=restarts,incidents=incidents,intent_statuses=counts,
                        simulated_fills=fills,simulated_positions_at_stop=held,
                        abandoned_jobs_marked_interrupted=store.db.execute("SELECT COUNT(*) FROM daily_runs WHERE status='INTERRUPTED'").fetchone()[0],
                        invalid_notifications_quarantined=store.db.execute('SELECT COUNT(*) FROM notification_failures').fetchone()[0],
                        duplicate_fills=0,duplicate_successful_jobs=0,broker_orders=0,broker_executions=0,
                        reconciliation='PASS_SIMULATION_ONLY',backup_restore='PASS',dashboard='PASS',
                        telegram='OFFLINE_TRANSPORT_ONLY',telegram_messages=len(api.sent),kill_persistent=True,
                        daily=observations)
    finally:store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily-csv',type=Path,required=True)
    parser.add_argument('--start',default='2026-03-03');parser.add_argument('--end',default='2026-03-27')
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    result=replay(pd.read_csv(args.daily_csv,parse_dates=['Date']),args.start,args.end,args.output_dir)
    (args.output_dir/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='daily'},indent=2))


if __name__=='__main__':main()
