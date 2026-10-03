"""Operations tests use fake data and never instantiate an IBKR client."""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import unittest

import pandas as pd

from bot.config import Settings
from bot.launchd import agent_definition
from bot.models import Signal
from bot.monitoring import dashboard_data
from bot.operations import due_jobs,session_schedule,tick,upcoming
from bot.storage import Store
from bot.web import create_app


class FakeData:
    def load(self,day):
        return pd.DataFrame({'Date':[day],'Ticker':['AAPL']})


class BrokenData:
    def load(self,day):raise RuntimeError('market data unavailable')


class FakeStrategy:
    strategy_id='2366a81673c5'
    def generate_signals(self,frame,day):
        return [Signal(self.strategy_id,'AAPL',day,'2026-10-02','2026-10-14',100.,'test fixture',9)]


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'ops.sqlite'
        self.store=Store(self.path)
        self.settings=Settings(trading_mode='DRY_RUN',trading_enabled=False,db_path=self.path)
    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_new_york_schedule_holidays_and_early_close(self):
        regular=session_schedule('2026-10-01')
        self.assertEqual(regular['daily'].astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M'),'16:45')
        early=session_schedule('2026-11-27')
        self.assertEqual(early['exits'].astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M'),'11:30')
        self.assertEqual(early['daily'].astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M'),'13:45')
        self.assertEqual(due_jobs('2026-11-26T17:00:00Z'),[])
        self.assertEqual(upcoming('2026-11-26T17:00:00Z',1)[0]['session'],'2026-11-27')

    def test_missed_daily_is_not_replayed(self):
        self.store.set_dry_run_enabled(True)
        result=tick(self.store,self.settings,FakeData(),FakeStrategy(),'2026-10-02T15:00:00Z')
        self.assertEqual(result,[])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],0)

    def test_end_to_end_duplicate_restart_and_scheduled_exit(self):
        self.store.set_dry_run_enabled(True)
        now='2026-10-01T21:00:00Z'
        first=tick(self.store,self.settings,FakeData(),FakeStrategy(),now)
        self.assertEqual([item['job'] for item in first],['data_refresh','daily'])
        self.assertEqual(first[1]['result']['orders_sent'],0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM order_intents WHERE status='DRY_RUN'").fetchone()[0],1)
        self.store.close();self.store=Store(self.path)
        self.assertEqual(tick(self.store,self.settings,FakeData(),FakeStrategy(),now),[])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],1)
        exit_check=tick(self.store,self.settings,FakeData(),FakeStrategy(),'2026-10-14T19:00:00Z')
        self.assertEqual(exit_check[0]['job'],'exits')
        self.assertEqual(exit_check[0]['result']['orders_sent'],0)
        self.assertEqual(exit_check[0]['result']['scheduled_exits'][0]['ticker'],'AAPL')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
        data=dashboard_data(self.store,self.settings)
        self.assertEqual(data['state'],'READY')
        self.assertEqual(data['signals'][0]['ticker'],'AAPL')
        self.assertEqual(data['orders'][0]['status'],'DRY_RUN')

    def test_market_data_error_is_persisted_and_blocks_next_job(self):
        self.store.set_dry_run_enabled(True)
        result=tick(self.store,self.settings,BrokenData(),FakeStrategy(),'2026-10-01T21:00:00Z')
        self.assertEqual(result[0]['job'],'data_refresh')
        self.assertIn('market data unavailable',result[0]['error'])
        self.assertEqual(self.store.operations_state()['state'],'DATA_ERROR')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0],0)

    def test_kill_switch_and_web_reads_without_paper_order(self):
        app=create_app(self.settings)
        client=app.test_client()
        page=client.get('/')
        self.assertEqual(page.status_code,200)
        token=re.search(rb'name="csrf" value="([^"]+)"',page.data).group(1).decode()
        self.assertEqual(client.post('/control/dry-run',data={'enabled':'1','csrf':'bad'}).status_code,403)
        self.assertEqual(client.post('/control/dry-run',data={'enabled':'1','csrf':token}).status_code,302)
        self.assertTrue(self.store.dry_run_enabled())
        self.assertEqual(client.get('/api/state').json['local_dry_run_enabled'],True)
        self.assertEqual(client.get('/api/state').json['trading_enabled'],False)
        client.post('/control/dry-run',data={'enabled':'0','csrf':token})
        self.assertEqual(tick(self.store,self.settings,FakeData(),FakeStrategy(),'2026-10-01T21:00:00Z'),[])
        with self.assertRaisesRegex(ValueError,'PAPER activation'):
            create_app(replace(self.settings,trading_mode='PAPER'))
        with self.assertRaises(ValueError):replace(self.settings,trading_mode='LIVE').validate()
        with self.assertRaisesRegex(ValueError,'DRY_RUN only'):
            tick(self.store,replace(self.settings,trading_mode='PAPER'),FakeData(),FakeStrategy(),'2026-10-01T21:00:00Z')
        with self.assertRaisesRegex(ValueError,'DRY_RUN only'):
            tick(self.store,replace(self.settings,trading_enabled=True),FakeData(),FakeStrategy(),'2026-10-01T21:00:00Z')

    def test_stale_scheduler_heartbeat_is_visible(self):
        self.store.set_dry_run_enabled(True)
        self.store.set_operations_state('READY')
        self.store.db.execute("UPDATE operations_state SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=1")
        self.store.db.commit()
        self.assertEqual(dashboard_data(self.store,self.settings)['state'],'ERROR')

    def test_launch_agent_is_locked_to_dry_run(self):
        agent=agent_definition('/some/python',Path(self.temp.name))
        self.assertTrue(agent['RunAtLoad'])
        self.assertTrue(agent['KeepAlive'])
        self.assertEqual(agent['EnvironmentVariables']['TRADING_MODE'],'DRY_RUN')
        self.assertEqual(agent['EnvironmentVariables']['TRADING_ENABLED'],'false')


if __name__=='__main__':unittest.main()
