"""Production-readiness regressions, using isolated ledgers and simulated APIs only."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from .config import Settings
from .calendar import exchange, next_session, exit_session
from .models import BrokerExecution, BrokerSnapshot, OrderIntent, Signal
from .runtime import synchronize
from .monitoring import dashboard_data
from .simulation import initialize, plan, settle, reconcile
from .storage import Store
from .telegram import __main__ as telegram_main


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'audit.sqlite'
        self.store=Store(self.path);self.cfg=Settings(trading_mode='DRY_RUN',db_path=self.path)
    def tearDown(self):self.store.close();self.temp.cleanup()

    def intent(self,key='entry',side='BUY',ticker='AAPL',order_id=1):
        intent=OrderIntent(key,'fixture',ticker,side,1,'2026-10-02' if side=='BUY' else '2026-10-14',
                           'test fixture','2026-10-01T21:00:00Z',9,'2026-10-14',
                           'LOO' if side=='BUY' else 'MOC',103. if side=='BUY' else None,'DU_TEST',100.)
        self.store.save_intent(intent,'PLANNED');self.store.order_claim(key,'DU_TEST');self.store.order_ack(key,order_id)
        return intent

    def test_execution_id_conflicting_payload_is_rejected(self):
        self.intent();fill=BrokerExecution('fill',1,'AAPL','BUY',1,100.,'2026-10-02','DU_TEST')
        self.store.sync_execution(fill)
        self.assertFalse(self.store.sync_execution(fill))
        with self.assertRaises(RuntimeError):self.store.sync_execution(replace(fill,price=200.))
        self.assertEqual(self.store.position('DU_TEST','AAPL')['avg_entry_price'],100.)

    def test_invalid_fill_price_is_rejected_atomically(self):
        self.intent()
        for price in (float('inf'),float('nan')):
            with self.assertRaises(ValueError):self.store.sync_execution(BrokerExecution('invalid',1,'AAPL','BUY',1,price,'2026-10-02','DU_TEST'))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],0)

    def test_replayed_executions_import_in_session_order(self):
        self.intent();self.intent('exit',side='SELL',order_id=2)
        buy=BrokerExecution('b',1,'AAPL','BUY',1,100.,'2026-10-02','DU_TEST')
        sell=BrokerExecution('s',2,'AAPL','SELL',1,110.,'2026-10-14','DU_TEST')
        class Broker:
            def snapshot(self,account):return BrokerSnapshot(account,1000.,executions=(sell,buy))
        synchronize(self.store,Broker(),'DU_TEST')
        self.assertEqual(self.store.positions('DU_TEST'),{})
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],2)

    def test_bad_notification_quarantined_without_fake_delivery(self):
        from .telegram.client import TelegramWorker
        class API:
            def __init__(self):self.sent=[]
            def send_message(self,user,text):self.sent.append(text)
        api=API()
        with self.store.tx() as db:
            self.store._enqueue(db,'bad','opened',{})
            self.store._enqueue(db,'valid','critical_error',{})
        worker=TelegramWorker(self.store,self.cfg,api,123456)
        self.assertEqual(worker.flush_notifications(),1)
        self.assertIsNone(self.store.db.execute("SELECT sent_at FROM notification_outbox WHERE event_key='bad'").fetchone()[0])
        self.assertEqual(self.store.db.execute("SELECT status FROM notification_failures WHERE event_key='bad'").fetchone()[0],'INVALID_PAYLOAD')
        self.assertEqual(worker.flush_notifications(),1) # Dedicated diagnostic, not fake execution.
        self.assertEqual(worker.flush_notifications(),0)

    def test_dashboard_totals_do_not_truncate_to_recent_200_fills(self):
        for n in range(105):
            ticker='TEST'+str(n)
            self.intent('buy'+str(n),ticker=ticker,order_id=2*n+1)
            self.store.sync_execution(BrokerExecution('b'+str(n),2*n+1,ticker,'BUY',1,100.,'2026-10-02','DU_TEST'))
            self.intent('sell'+str(n),side='SELL',ticker=ticker,order_id=2*n+2)
            self.store.sync_execution(BrokerExecution('s'+str(n),2*n+2,ticker,'SELL',1,110.,'2026-10-14','DU_TEST'))
        view=dashboard_data(self.store,self.cfg)
        self.assertEqual(view['pnl_usd'],1050.)
        self.assertEqual(len(view['trades']),105)
        self.assertLessEqual(len(view['executions']),50)

    def test_abandoned_run_is_marked_only_after_exclusive_lock(self):
        run=self.store.run_start('daily','DRY_RUN','2026-10-01')
        competing=Store(self.path)
        try:
            with self.assertRaises(RuntimeError):competing.run_start('daily','DRY_RUN','2026-10-01')
            self.assertEqual(competing.db.execute('SELECT status FROM daily_runs WHERE run_id=?',(run,)).fetchone()[0],'RUNNING')
        finally:competing.close()
        self.store.close();self.store=Store(self.path)
        recovered=self.store.run_start('daily','DRY_RUN','2026-10-01')
        self.assertEqual(self.store.db.execute('SELECT status FROM daily_runs WHERE run_id=?',(run,)).fetchone()[0],'INTERRUPTED')
        self.store.run_end(recovered,'OK',{})

    def test_simulated_position_price_corruption_blocks_reconcile(self):
        class Strategy:
            strategy_id='fixture'
            def generate_signals(self,frame,day):return [Signal('fixture','AAPL',day,'2026-10-02','2026-10-14',100.,'fixture',9)]
        frame=pd.DataFrame(dict(Date=[pd.Timestamp('2026-10-02')],Ticker=['AAPL'],Open=[100.],Close=[101.]))
        initialize(self.store,self.cfg);plan(self.store,self.cfg,Strategy(),frame,'2026-10-01')
        settle(self.store,self.cfg,frame,'2026-10-02','2026-10-02T21:00:00Z')
        self.store.db.execute('UPDATE simulated_positions SET avg_entry_price=999');self.store.db.commit()
        with self.assertRaises(ValueError):reconcile(self.store,self.cfg)

    def test_broken_notification_and_reply_cannot_starve_kill(self):
        class API:
            def send_message(self,*args):raise RuntimeError('simulated delivery failure')
            def get_updates(self,offset):
                return [{'update_id':1,'message':{'from':{'id':123456},'chat':{'id':123456,'type':'private'},'text':'/status'}},
                        {'update_id':2,'message':{'from':{'id':123456},'chat':{'id':123456,'type':'private'},'text':'/kill'}}]
        with self.store.tx() as db:self.store._enqueue(db,'bad','opened',{})
        # Stop after one controlled loop; never contact Telegram or use a real token.
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'UNIT_TEST_PLACEHOLDER','TELEGRAM_ALLOWED_USER_ID':'123456'},clear=True), \
             patch.object(telegram_main,'from_env',return_value=self.cfg), \
             patch.object(telegram_main,'BotAPI',return_value=API()), \
             patch.object(telegram_main,'Store',return_value=self.store), \
             patch.object(telegram_main.time,'sleep',side_effect=KeyboardInterrupt):
            try:telegram_main.main()
            except KeyboardInterrupt:pass
        self.store=Store(self.path)
        self.assertTrue(self.store.kill_switch_enabled())
        self.assertEqual(self.store.telegram_offset(),2)

    def test_integrated_holiday_early_close_ninth_session_and_restarts(self):
        from .production_audit import replay
        start,end='2026-11-25','2026-12-15'
        dates=exchange(start).schedule.loc[start:end].index
        panel=pd.DataFrame([dict(Date=d,Ticker='AAPL',Open=100.,High=102.,Low=99.,Close=101.,Volume=1000) for d in dates])
        class FixtureStrategy:
            strategy_id='fixture'
            def generate_signals(self,frame,day):
                if day!=start:return []
                entry=next_session(day)
                return [Signal('fixture','AAPL',day,entry,exit_session(entry,9),100.,'synthetic lifecycle fixture',9)]
        with patch('bot.production_audit.FrozenSwingV2',return_value=FixtureStrategy()):
            report=replay(panel,start,end,Path(self.temp.name)/'multi')
        self.assertEqual(next_session(start),'2026-11-27')
        self.assertEqual(exit_session('2026-11-27',9),'2026-12-09')
        self.assertNotIn('2026-11-26',[r['session'] for r in report['daily']])
        self.assertEqual(report['simulated_fills'],2)
        self.assertEqual(report['simulated_positions_at_stop'],0)
        self.assertEqual(report['broker_orders'],0)
        self.assertEqual(report['abandoned_jobs_marked_interrupted'],1)
        self.assertEqual(report['duplicate_fills'],0)
        self.assertTrue(report['kill_persistent'])


if __name__=='__main__':unittest.main()
