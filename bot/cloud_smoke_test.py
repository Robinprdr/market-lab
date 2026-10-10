"""Replay one frozen signal session, not a strategy backtest, in a NEW isolated ledger."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from .backup import copy_database
from .config import Settings
from .simulation import initialize, plan, settle, positions, reconcile
from .storage import Store
from .strategy import FrozenSwingV2
from .telegram.client import TelegramWorker
from .web import create_app


class CapturedTelegram:
    def __init__(self):self.messages=[]
    def send_message(self,chat_id,text):self.messages.append(text);return {'message_id':len(self.messages)}


def scenario(panel,day,directory,api=None,user_id=5561255226):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'scenario.sqlite'
    if path.exists():raise ValueError('Scenario requires a new database')
    cfg=Settings(trading_mode='DRY_RUN',db_path=path);store=Store(path)
    api=api or CapturedTelegram()
    try:
        frozen=FrozenSwingV2();frame=panel[panel.Date.le(pd.Timestamp(day))]
        initialize(store,cfg)
        run=store.run_start('daily','DRY_RUN',day)
        planned=plan(store,cfg,frozen,frame,day);store.run_end(run,'OK',planned)
        plans=store.db.execute("SELECT * FROM order_intents WHERE status='DRY_RUN'").fetchall()
        if not plans:raise ValueError('No eligible frozen signal in this session')
        entry=plans[0]['intended_entry_date'];exit_day=plans[0]['target_exit_date']
        if any(p['target_exit_date']!=exit_day for p in plans):raise ValueError('Unexpected horizons')
        entered=settle(store,cfg,panel,entry)
        if not positions(store):raise ValueError('All simulated entry prices exceeded unchanged limit caps')
        duplicate=settle(store,cfg,panel,entry)
        view=create_app(cfg).test_client().get('/api/state').json
        assert view['simulated_positions'] and not view['positions']
        TelegramWorker(store,cfg,api,user_id).flush_notifications()
        store.close();store=Store(path) # Actual disconnect/reopen between entry and exit.
        restart_positions=len(positions(store));reconcile(store,cfg)
        exited=settle(store,cfg,panel,exit_day)
        assert not positions(store)
        assert settle(store,cfg,panel,exit_day)['simulated_exits']==0
        TelegramWorker(store,cfg,api,user_id).flush_notifications()
        for table in ('orders','executions','positions'):
            assert store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        final_reconciliation=reconcile(store,cfg)
        snapshot=copy_database(path,directory/'backup.sqlite')
        restored=copy_database(snapshot,directory/'restored.sqlite')
        recovered=Store(restored)
        try:
            assert recovered.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]==store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]
            assert reconcile(recovered,replace(cfg,db_path=restored))['status']=='PASS'
        finally:recovered.close()
        html=create_app(cfg).test_client().get('/').data.decode()
        assert 'TEST / DRY_RUN' in html
        return dict(strategy=frozen.strategy_id,signal_session=day,entry_session=entry,exit_session=exit_day,
                    planned=planned,entry=entered,exit=exited,restart_positions=restart_positions,
                    duplicate_entries=duplicate['simulated_entries'],final_reconciliation=final_reconciliation,
                    broker_orders=0,broker_executions=0,backup_restore='PASS',dashboard='PASS',
                    telegram='REAL_TEST_DELIVERY' if not isinstance(api,CapturedTelegram) else 'SIMULATED_TRANSPORT_PASS',
                    telegram_messages=len(api.messages) if isinstance(api,CapturedTelegram) else None)
    finally:store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily-csv',type=Path,required=True)
    parser.add_argument('--signal-date',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--telegram',action='store_true',help='Send only clearly marked TEST events to the authorized private chat')
    args=parser.parse_args();api=None;user=5561255226
    if args.telegram:
        from .telegram_smoke_test import credentials
        from .telegram.client import BotAPI
        token,user=credentials();api=BotAPI(token)
        if not api.get_me().get('is_bot'):raise ValueError('Bot identity not confirmed')
    result=scenario(pd.read_csv(args.daily_csv,parse_dates=['Date']),args.signal_date,args.output_dir,api,user)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
