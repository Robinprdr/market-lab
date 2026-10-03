"""No network access or broker order is used in these Telegram tests."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from bot.config import Settings
from bot.models import BrokerExecution,OrderIntent,Signal
from bot.portfolio import entry_intent
from bot.runtime import _submit
from bot.storage import Store
from bot.telegram.client import BotAPI,TelegramWorker,event_message


class FakeAPI:
    def __init__(self):self.sent=[]
    def send_message(self,chat_id,text):self.sent.append((chat_id,text))


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'ledger.sqlite')
        self.settings=Settings(trading_mode='DRY_RUN',trading_enabled=False,db_path=self.store.path)
        self.api=FakeAPI()
        self.worker=TelegramWorker(self.store,self.settings,self.api,123456)
    def tearDown(self):self.store.close();self.temp.cleanup()

    @staticmethod
    def update(command,user=123456,chat=123456,chat_type='private'):
        return dict(update_id=1,message={'from':{'id':user},'chat':{'id':chat,'type':chat_type},'text':command})

    def test_unauthorized_user_and_chat_are_ignored(self):
        self.assertFalse(self.worker.process_update(self.update('/kill',user=99)))
        self.assertFalse(self.worker.process_update(self.update('/kill',chat=99)))
        self.assertFalse(self.worker.process_update(self.update('/kill',chat_type='group')))
        self.assertFalse(self.store.kill_switch_enabled())
        self.assertEqual(self.api.sent,[])

    def test_status_positions_kill_persistence_and_no_resume(self):
        self.assertTrue(self.worker.process_update(self.update('/status')))
        self.assertIn('DRY_RUN',self.api.sent[-1][1])
        self.assertTrue(self.worker.process_update(self.update('/positions')))
        self.assertEqual(self.api.sent[-1][1],'Aucune position exécutée.')
        self.assertTrue(self.worker.process_update(self.update('/kill')))
        self.assertIn('Aucun nouvel ordre',self.api.sent[-1][1])
        self.assertTrue(self.store.kill_switch_enabled())
        self.assertFalse(self.worker.process_update(self.update('/resume')))
        self.assertTrue(self.store.kill_switch_enabled())
        with self.assertRaisesRegex(ValueError,'KILL_SWITCH_ACTIVE'):
            self.store.set_dry_run_enabled(True)
        self.assertFalse(self.store.dry_run_enabled())
        self.store.close();self.store=Store(Path(self.temp.name)/'ledger.sqlite')
        self.assertTrue(self.store.kill_switch_enabled())
        self.worker.store=self.store
        self.assertTrue(self.worker.process_update(self.update('/kill')))
        self.assertIn('déjà actif',self.api.sent[-1][1])

    def test_kill_blocks_paper_submission_without_broker_call(self):
        class Broker:
            calls=0
            def submit(self,intent):self.calls+=1;return 1
        paper=replace(self.settings,trading_mode='PAPER',trading_enabled=True,allowed_account_id='DU12345')
        intent=OrderIntent('test','strategy','AAPL','BUY',1,'2026-10-02','test','2026-10-01T00:00:00Z',
                           9,'2026-10-14','LOO',101.,'DU12345',100.)
        self.store.save_intent(intent,'PLANNED')
        self.store.activate_kill_switch('telegram')
        broker=Broker()
        with self.assertRaisesRegex(ValueError,'KILL_SWITCH'):
            _submit(self.store,broker,intent,paper)
        self.assertEqual(broker.calls,0)
        self.assertEqual(self.store.intent('test')['status'],'PLANNED')

    def test_only_real_fills_create_entry_and_exit_alerts(self):
        paper=replace(self.settings,trading_mode='PAPER',trading_enabled=True,allowed_account_id='DU12345')
        signal=Signal('2366a81673c5','NVDA','2026-10-01','2026-10-02','2026-10-14',100.,'fixture',9)
        self.store.save_signal(signal)
        self.assertEqual(self.store.pending_notifications(),[])
        entry,_=entry_intent(signal,self.store,__import__('bot.models',fromlist=['BrokerSnapshot']).BrokerSnapshot('DU12345',10000.),paper)
        entry=replace(entry,quantity=2)
        self.store.save_intent(entry,'PLANNED');self.store.order_claim(entry.intent_id,'DU12345');self.store.order_ack(entry.intent_id,101)
        self.store.sync_execution(BrokerExecution('e1',101,'NVDA','BUY',1,100.,'2026-10-02','DU12345'))
        self.store.sync_execution(BrokerExecution('e2',101,'NVDA','BUY',1,100.,'2026-10-02','DU12345'))
        self.store.sync_execution(BrokerExecution('e2',101,'NVDA','BUY',1,100.,'2026-10-02','DU12345'))
        self.assertEqual([e['kind'] for e in self.store.pending_notifications()],['opened'])
        exit_intent=replace(entry,intent_id='exit-1',side='SELL',intended_entry_date='2026-10-14',
                            order_type='MOC',limit_price=None)
        self.store.save_intent(exit_intent,'PLANNED');self.store.order_claim('exit-1','DU12345');self.store.order_ack('exit-1',102)
        self.store.sync_execution(BrokerExecution('e3',102,'NVDA','SELL',1,110.,'2026-10-14','DU12345'))
        self.assertEqual([e['kind'] for e in self.store.pending_notifications()],['opened'])
        self.store.sync_execution(BrokerExecution('e4',102,'NVDA','SELL',1,110.,'2026-10-14','DU12345'))
        self.assertEqual([e['kind'] for e in self.store.pending_notifications()],['opened','closed'])
        self.assertEqual(self.worker.flush_notifications(),2)
        self.assertIn('LONG NVDA',self.api.sent[0][1])
        self.assertIn('NVDA clôturé',self.api.sent[1][1])
        self.assertIn('+20,00 $',self.api.sent[1][1])
        self.assertIn('+10,00 %',self.api.sent[1][1])
        self.assertNotIn('sortie prévue',self.api.sent[0][1].lower())
        self.assertEqual(self.worker.flush_notifications(),0)

    def test_daily_summary_and_critical_errors_no_refusal_spam(self):
        run=self.store.run_start('daily','DRY_RUN','2026-10-01')
        self.store.run_end(run,'OK',{'refused':10,'decisions':[{'accepted':False,'reason':'filter'}]})
        self.store.error(None,'RECONCILIATION_REQUIRED','private technical detail')
        self.store.error(None,'DATA_ERROR','network detail')
        kinds=[e['kind'] for e in self.store.pending_notifications()]
        self.assertEqual(kinds,['daily','reconciliation','critical_error'])
        self.worker.flush_notifications()
        self.assertIn('Résumé',self.api.sent[0][1])
        self.assertNotIn('filter',' '.join(text for _,text in self.api.sent))
        self.assertNotIn('private technical detail',' '.join(text for _,text in self.api.sent))

    def test_api_errors_do_not_expose_token_and_offset_persists(self):
        client=BotAPI('secret-test-token')
        with patch('bot.telegram.client.request.urlopen',side_effect=URLError('secret-test-token')):
            with self.assertRaises(RuntimeError) as exc:
                client.get_updates(1)
        self.assertNotIn('secret-test-token',str(exc.exception))
        self.store.mark_telegram_update(7)
        self.store.close();self.store=Store(Path(self.temp.name)/'ledger.sqlite')
        self.assertEqual(self.store.telegram_offset(),7)


if __name__=='__main__':unittest.main()
