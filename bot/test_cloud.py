"""Deployment safety tests: no network, credentials, broker or live order."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from bot.backup import copy_database
from bot.cloud import cloud_settings, scheduler_lease, tick, record_health, health
from bot.cloud_watch import inspect, gateway_status
from bot.config import Settings
from bot.deploy.bundle import members, ROOT
from bot.models import Signal
from bot.operations import due_jobs, session_schedule
from bot.simulation import initialize, plan, settle, positions, reconcile
from bot.storage import Store
from bot.telegram.client import TelegramWorker
from bot.cloud_smoke_test import CapturedTelegram
from bot.web import create_app


class Strategy:
    strategy_id='2366a81673c5'
    def generate_signals(self,frame,day):
        return [Signal(self.strategy_id,'AAPL',day,'2026-10-02','2026-10-14',100.,'fixture',9)]


class Data:
    def load(self,day):
        return pd.DataFrame(dict(Date=[pd.Timestamp(day)],Ticker=['AAPL'],Open=[100.],Close=[101.]))


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'dry.sqlite'
        self.cfg=Settings(trading_mode='DRY_RUN',db_path=self.path);self.store=Store(self.path)
        initialize(self.store,self.cfg)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def planned(self):return plan(self.store,self.cfg,Strategy(),Data().load('2026-10-01'),'2026-10-01')

    def test_service_mode_guards(self):
        for cfg in (replace(self.cfg,trading_mode='LIVE'),replace(self.cfg,trading_mode='PAPER'),replace(self.cfg,trading_enabled=True)):
            with self.assertRaises(ValueError):initialize(self.store,cfg)

    def test_explicit_isolated_db_required(self):
        with patch.dict(os.environ,{'TRADING_MODE':'DRY_RUN','TRADING_ENABLED':'false'},clear=True):
            with self.assertRaises(ValueError):cloud_settings()
        with patch.dict(os.environ,{'TRADING_MODE':'DRY_RUN','BOT_DB_PATH':str(Settings.db_path)},clear=True):
            with self.assertRaises(ValueError):cloud_settings()

    def test_wrong_account_rejected(self):
        with patch.dict(os.environ,{'TRADING_MODE':'DRY_RUN','BOT_DB_PATH':str(self.path),'IBKR_ALLOWED_ACCOUNT_ID':'DU_OTHER'},clear=True):
            with self.assertRaises(ValueError):cloud_settings()

    def test_scheduler_exclusive_lease_released_on_restart(self):
        with scheduler_lease(self.path):
            with self.assertRaises(RuntimeError):
                with scheduler_lease(self.path):pass
        with scheduler_lease(self.path):pass

    def test_preopen_deadline(self):
        self.assertIn(('preopen','2026-10-09'),due_jobs('2026-10-09T13:20:00Z'))
        self.assertNotIn(('preopen','2026-10-09'),due_jobs('2026-10-09T13:25:00Z'))
        self.assertNotIn(('preopen','2026-10-09'),due_jobs('2026-10-09T13:35:00Z'))

    def test_preopen_missing_prior_plan_blocks(self):
        self.store.set_dry_run_enabled(True)
        tick(self.store,self.cfg,Data(),Strategy(),'2026-10-09T13:20:00Z')
        self.assertEqual(self.store.operations_state()['state'],'DATA_ERROR')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_preopen_valid_plan_remains_dry_run(self):
        self.store.set_dry_run_enabled(True)
        tick(self.store,self.cfg,Data(),Strategy(),'2026-10-01T21:00:00Z')
        result=tick(self.store,self.cfg,Data(),Strategy(),'2026-10-02T13:20:00Z')
        self.assertEqual(result[-1]['job'],'preopen')
        self.assertEqual(len(result[-1]['result']['prepared_entries']),1)
        self.assertEqual(result[-1]['result']['orders_sent'],0)

    def test_gateway_disconnect_reconnect_is_not_authentication(self):
        with patch('bot.cloud_watch.socket.create_connection',side_effect=OSError):
            self.assertEqual(gateway_status(True)['state'],'SOCKET_UNREACHABLE')
            self.assertEqual(gateway_status(False)['state'],'NOT_REQUIRED_FOR_DRY_RUN')
        with patch('bot.cloud_watch.socket.create_connection'):
            status=gateway_status(True)
            self.assertEqual(status['state'],'SOCKET_REACHABLE_ONLY');self.assertFalse(status['api_authenticated'])

    def test_dst_and_half_day(self):
        self.assertEqual(session_schedule('2026-10-30')['preopen'].hour,13)
        self.assertEqual(session_schedule('2026-11-02')['preopen'].hour,14)
        self.assertEqual(session_schedule('2026-11-27')['daily'].hour,18)
        self.assertEqual(due_jobs('2026-10-10T13:20:00Z'),[])

    def test_completed_bar_only(self):
        self.planned()
        with self.assertRaises(ValueError):settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T15:00:00Z')
        self.assertEqual(len(positions(self.store)),0)

    def test_restart_simulation_and_duplicate_prevention(self):
        self.assertEqual(self.planned()['accepted'],1);self.planned()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],1)
        self.assertEqual(settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T21:00:00Z')['simulated_entries'],1)
        self.assertEqual(settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T21:00:00Z')['simulated_entries'],0)
        self.store.close();self.store=Store(self.path)
        self.assertEqual(len(positions(self.store)),1)
        self.assertEqual(settle(self.store,self.cfg,Data().load('2026-10-14'),'2026-10-14','2026-10-14T21:00:00Z')['simulated_exits'],1)
        self.assertEqual(settle(self.store,self.cfg,Data().load('2026-10-14'),'2026-10-14','2026-10-14T21:00:00Z')['simulated_exits'],0)
        self.assertEqual(reconcile(self.store,self.cfg)['status'],'PASS')
        for table in ('orders','executions','positions'):self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)

    def test_price_cap_is_not_relaxed(self):
        self.planned();bars=Data().load('2026-10-02');bars['Open']=104.
        self.assertEqual(settle(self.store,self.cfg,bars,'2026-10-02','2026-10-02T21:00:00Z')['simulated_entries'],0)
        self.assertEqual(self.store.db.execute('SELECT status FROM order_intents').fetchone()[0],'SIMULATED_NO_FILL')

    def test_no_accidental_short_or_unplanned_exit(self):
        self.assertEqual(settle(self.store,self.cfg,Data().load('2026-10-14'),'2026-10-14','2026-10-14T21:00:00Z')['simulated_exits'],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0],0)

    def test_stale_simulation_is_not_silently_replayed(self):
        self.planned()
        with self.assertRaises(ValueError):settle(self.store,self.cfg,Data().load('2026-10-05'),'2026-10-05','2026-10-05T21:00:00Z')

    def test_corrupt_simulated_ledger_rejected(self):
        self.store.db.execute("INSERT INTO simulated_positions VALUES('AAPL','fixture',1,'2026-10-02','2026-10-14',100)");self.store.db.commit()
        with self.assertRaises(ValueError):reconcile(self.store,self.cfg)
        with self.assertRaises(ValueError):self.planned()

    def test_uncertain_intent_is_never_retried(self):
        self.planned();self.store.db.execute("UPDATE order_intents SET status='UNCERTAIN'");self.store.db.commit()
        with self.assertRaises(ValueError):initialize(self.store,self.cfg)
        with self.assertRaises(ValueError):self.planned()

    def test_service_actual_dry_run_startup(self):
        env={k:v for k,v in os.environ.items() if k not in ('TELEGRAM_BOT_TOKEN','TELEGRAM_ALLOWED_USER_ID','APCA_API_KEY_ID','APCA_API_SECRET_KEY','IBKR_ALLOWED_ACCOUNT_ID')}
        env.update(TRADING_MODE='DRY_RUN',TRADING_ENABLED='false',BOT_DB_PATH=str(Path(self.tmp.name)/'startup.sqlite'))
        proc=subprocess.run([sys.executable,'-m','bot.cloud','--once'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout),[])

    def test_cash_and_exposure_guards_preserved(self):
        result=plan(self.store,replace(self.cfg,initial_equity_usd=10),Strategy(),Data().load('2026-10-01'),'2026-10-01')
        self.assertEqual(result['accepted'],0);self.assertEqual(result['refused'],1)

    def test_kill_survives_restart_and_blocks_simulation(self):
        self.store.activate_kill_switch('TEST');self.store.close();self.store=Store(self.path)
        self.assertTrue(self.store.kill_switch_enabled())
        with self.assertRaises(ValueError):self.planned()
        with self.assertRaises(ValueError):settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T21:00:00Z')
        with self.assertRaises(ValueError):self.store.set_dry_run_enabled(True)
        self.assertEqual(tick(self.store,self.cfg,Data(),Strategy(),'2026-10-01T21:00:00Z'),[])

    def test_kill_during_signal_generation_blocks_intents(self):
        store=self.store
        class Killed(Strategy):
            def generate_signals(self,frame,day):
                store.activate_kill_switch('TEST');return super().generate_signals(frame,day)
        with self.assertRaises(ValueError):plan(self.store,self.cfg,Killed(),Data().load('2026-10-01'),'2026-10-01')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],0)

    def test_data_failure_blocks_strategy_and_redacts_credentials(self):
        class Broken:
            def load(self,day):raise RuntimeError('https://host.invalid/private-token-value')
        self.store.set_dry_run_enabled(True)
        result=tick(self.store,self.cfg,Broken(),Strategy(),'2026-10-01T21:00:00Z')
        self.assertEqual(result[0]['error'],'JOB_FAILED')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM signals').fetchone()[0],0)
        self.assertNotIn('private-token-value',repr(list(self.store.db.iterdump())))

    def test_daily_requires_data_refresh(self):
        self.store.set_dry_run_enabled(True)
        with patch('bot.cloud.due_jobs',return_value=[('daily','2026-10-01')]):
            self.assertEqual(tick(self.store,self.cfg,Data(),Strategy()),[])
        self.assertEqual(self.store.operations_state()['state'],'DATA_ERROR')

    def test_restart_scheduler_completed_job_not_repeated(self):
        self.store.set_dry_run_enabled(True)
        first=tick(self.store,self.cfg,Data(),Strategy(),'2026-10-01T21:00:00Z')
        self.assertEqual([r['job'] for r in first],['data_refresh','daily'])
        self.assertEqual(first[1]['result']['accepted'],1)
        self.store.close();self.store=Store(self.path)
        self.assertEqual(tick(self.store,self.cfg,Data(),Strategy(),'2026-10-01T21:00:00Z'),[])

    def test_no_broker_on_gateway_failure_or_unknown_state(self):
        self.store.set_dry_run_enabled(True)
        with patch('bot.broker_ibkr.IBKRPaperBroker',side_effect=AssertionError('Broker forbidden')):
            tick(self.store,self.cfg,Data(),Strategy(),'2026-10-01T21:00:00Z')
        self.assertEqual(health(self.store)['broker'],'DISABLED_BY_DRY_RUN_POLICY')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)

    def test_backup_restore_wal_and_no_overwrite(self):
        self.planned();self.store.activate_kill_switch('TEST')
        backup=copy_database(self.path,Path(self.tmp.name)/'backup.sqlite')
        restored=copy_database(backup,Path(self.tmp.name)/'restored.sqlite')
        recovered=Store(restored)
        try:
            self.assertTrue(recovered.kill_switch_enabled());self.assertEqual(recovered.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],1)
            self.assertEqual(recovered.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:recovered.close()
        with self.assertRaises(ValueError):copy_database(backup,self.path)

    def test_health_stale_disk_alert_dedup(self):
        first=inspect(self.store,min_free=10**30)
        self.assertIn('SCHEDULER_STALE',first['issues']);self.assertIn('DISK_LOW',first['issues'])
        count=len(self.store.pending_notifications());inspect(self.store,min_free=10**30)
        self.assertEqual(len(self.store.pending_notifications()),count)
        record_health(self.store,'scheduler_heartbeat',{})
        self.assertNotIn('SCHEDULER_STALE',inspect(self.store,min_free=0)['issues'])

    def test_telegram_test_label_private_user_and_persisted_kill(self):
        api=CapturedTelegram();worker=TelegramWorker(self.store,self.cfg,api,5561255226)
        self.planned();settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T21:00:00Z')
        worker.flush_notifications();self.assertTrue(all(t.startswith('[TEST / DRY_RUN') for t in api.messages))
        bad={'message':{'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'/kill'}}
        self.assertFalse(worker.process_update(bad));self.assertFalse(self.store.kill_switch_enabled())
        good={'message':{'from':{'id':5561255226},'chat':{'id':5561255226,'type':'private'},'text':'/positions'}}
        worker.process_update(good);self.assertIn('positions simulées',api.messages[-1])
        good['message']['text']='/kill';worker.process_update(good)
        self.assertTrue(self.store.kill_switch_enabled())
        good['message']['text']='/resume';self.assertFalse(worker.process_update(good))

    def test_dashboard_separates_simulated_and_broker_positions(self):
        self.planned();settle(self.store,self.cfg,Data().load('2026-10-02'),'2026-10-02','2026-10-02T21:00:00Z')
        client=create_app(self.cfg).test_client();view=client.get('/api/state').json
        self.assertEqual(view['positions'],[]);self.assertEqual(len(view['simulated_positions']),1)
        self.assertIn('TEST / DRY_RUN',client.get('/').data.decode())

    def test_linux_units_and_bootstrap_are_safe_static_checks(self):
        directory=ROOT/'bot/deploy/systemd'
        for name in ('scheduler','dashboard','telegram'):
            text=(directory/f'market-lab-{name}.service').read_text()
            self.assertIn('User=marketlab',text);self.assertIn('NoNewPrivileges=true',text)
            self.assertIn('Restart=on-failure',text);self.assertNotIn('bot.runtime',text)
        for script in ('install.sh','manage.sh','start-gateway'):
            subprocess.run(['bash','-n',str(ROOT/'bot/deploy'/script)],check=True)
        self.assertIn("listen='127.0.0.1:8765'",(ROOT/'bot/cloud_service.py').read_text())
        self.assertNotIn('enable --now',(ROOT/'bot/deploy/install.sh').read_text())

    def test_bundle_no_intraday_data_sqlite_or_secrets(self):
        files=members()
        self.assertIn('results/research_v2/frozen_candidates.json.sha256',files)
        self.assertIn('research/research_v2/protocol.json',files)
        self.assertFalse(any(n.startswith('data/cache/') or n.endswith(('.sqlite','.csv.zip','.env')) for n in files))
        for key in ('TELEGRAM_BOT_TOKEN','APCA_API_KEY_ID','APCA_API_SECRET_KEY'):
            value=os.getenv(key)
            if value and len(value)>16:
                for name in files:self.assertNotIn(value.encode(),(ROOT/name).read_bytes(),name)


if __name__=='__main__':unittest.main()
