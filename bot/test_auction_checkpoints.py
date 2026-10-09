"""Disconnected workflow tests: fake broker only, no socket or real order."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bot.auction_checkpoints import Checkpoints, ACCOUNT, TICKER, STRATEGY, phase_window
from bot.config import Settings
from bot.models import BrokerSnapshot, BrokerOrder, BrokerPosition, BrokerExecution
from bot.storage import Store

DAY='2026-10-09'

class FakeBroker:
    def __init__(self):
        self.audit=SimpleNamespace(emit=lambda *a,**k:None)
        self.stop_path=Path('/no-auction-stop-file')
        self.sent=[];self.orders={};self.executions=[];self.metadata={};self.positions={};self.next_id=100
        self.connections=0;self.closed=0;self.fail=False;self.lose_ack=False;self.account=ACCOUNT
    def close(self):self.closed+=1
    def reference(self):return 100.
    def reserve(self,i):self.next_id+=1;return self.next_id
    def send(self,i,oid):
        self.sent.append((i.side,oid))
        if self.fail:raise TimeoutError('network uncertain')
        self.orders[i.intent_id]=dict(ref=i.intent_id,oid=oid,perm_id=10000+oid,account=ACCOUNT,ticker=TICKER,
                                     currency='USD',security_type='STK',side=i.side,quantity=1,
                                     order_type='LMT' if i.side=='BUY' else 'MOC',tif='OPG' if i.side=='BUY' else 'DAY',
                                     limit_price=i.limit_price,status='Submitted',reason='',kind='open')
        if self.lose_ack:raise TimeoutError('ack lost after broker accepted')
    def evidence(self):
        self.connections+=1
        active=[BrokerOrder(o['oid'],o['ref'],TICKER,o['side'],1,o['status'],ACCOUNT)
                for o in self.orders.values() if o['status'] in ('Submitted','PreSubmitted')]
        s=BrokerSnapshot(self.account,10000,dict(self.positions),tuple(active),tuple(self.executions),
                         10000,10000,'EUR',{'USD':10000},{},{'USD':10000},{'USD':10000})
        return s,list(self.orders.values()),dict(self.metadata),{}
    def fill(self,side):
        o=next(o for o in self.orders.values() if o['side']==side)
        o['status']='Filled';o['kind']='completed'
        eid='fill-'+side
        self.executions.append(BrokerExecution(eid,o['oid'],TICKER,side,1,100,DAY,ACCOUNT))
        self.metadata[eid]=dict(execution_id=eid,oid=o['oid'],perm_id=o['perm_id'],account=ACCOUNT,
                               currency='USD',security_type='STK',ticker=TICKER,
                               exchange_time='20261009 '+('09:30:01' if side=='BUY' else '16:00:01')+' US/Eastern')
        self.positions={TICKER:BrokerPosition(TICKER,1,100)} if side=='BUY' else {}

class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'ledger.sqlite';self.store=Store(self.path)
        self.cfg=Settings(allowed_account_id=ACCOUNT,trading_enabled=True,ibkr_port=4002)
        self.broker=FakeBroker()
    def tearDown(self):self.store.close();self.temp.cleanup()
    def workflow(self,at='2026-10-09T13:20:00Z'):
        return Checkpoints(self.store,self.broker,self.cfg,DAY,at)
    def enter(self):return self.workflow().run('enter')
    def arm(self):return self.workflow('2026-10-09T13:35:00Z').run('arm-exit')
    def verify(self):return self.workflow('2026-10-09T20:10:00Z').run('verify-close')
    def test_enter_idempotent(self):
        self.enter();r=self.enter();self.assertTrue(r['idempotent']);self.assertEqual(len(self.broker.sent),1)
    def test_no_fill_no_sell(self):
        self.enter()
        with self.assertRaisesRegex(RuntimeError,'not Filled'):self.arm()
        self.assertEqual([s for s,_ in self.broker.sent],['BUY'])
    def test_missing_entry_no_sell(self):
        with self.assertRaisesRegex(RuntimeError,'not Filled'):self.arm()
        self.assertEqual(self.broker.sent,[])
    def test_arm_fill_and_duplicate_prevention(self):
        self.enter();self.broker.fill('BUY');self.arm();r=self.arm()
        self.assertTrue(r['idempotent']);self.assertEqual([s for s,_ in self.broker.sent],['BUY','SELL'])
    def test_closed_reconciliation_and_idempotent_verify(self):
        self.enter();self.broker.fill('BUY');self.arm();self.broker.fill('SELL')
        r=self.verify();self.assertEqual((r['OPG'],r['MOC'],r['positions']),('PASS','PASS',0))
        self.verify();self.assertEqual(len(self.broker.sent),2);self.assertFalse(self.store.positions(ACCOUNT))
    def test_restart_stale_sqlite_imports_real_fill(self):
        self.enter();self.broker.fill('BUY');self.assertFalse(self.store.positions(ACCOUNT))
        self.store.close();self.store=Store(self.path)
        self.arm();self.assertEqual(self.store.position(ACCOUNT,TICKER)['quantity'],1)
        self.assertGreaterEqual(self.broker.connections,4)
    def test_crash_after_transmit_ack_recovered_no_resend(self):
        self.broker.lose_ack=True
        with self.assertRaises(TimeoutError):self.enter()
        self.store.close();self.store=Store(self.path);self.broker.lose_ack=False
        r=self.enter();self.assertTrue(r['idempotent']);self.assertEqual(len(self.broker.sent),1)
    def test_uncertain_absent_never_resubmits(self):
        self.broker.fail=True
        with self.assertRaises(TimeoutError):self.enter()
        self.broker.fail=False
        with self.assertRaisesRegex(RuntimeError,'uncertain'):self.enter()
        self.assertEqual(len(self.broker.sent),1)
    def test_broker_position_truth_refuses_stale_local(self):
        self.enter();self.broker.fill('BUY');self.workflow().recover();self.broker.positions={}
        with self.assertRaisesRegex(RuntimeError,'disagree'):self.arm()
        self.assertEqual(len(self.broker.sent),1)
    def test_filled_status_without_execution_refused(self):
        self.enter();self.broker.orders[self.workflow().ref('BUY')]['status']='Filled'
        with self.assertRaisesRegex(RuntimeError,'without'):self.arm()
    def test_wrong_account(self):
        self.broker.account='DU_OTHER'
        with self.assertRaisesRegex(RuntimeError,'Wrong'):self.enter()
        with self.assertRaises(ValueError):Checkpoints(self.store,self.broker,replace(self.cfg,allowed_account_id='DU_OTHER'),DAY)
        self.assertFalse(self.broker.sent)
    def test_live_blocked(self):
        with self.assertRaises(ValueError):Checkpoints(self.store,self.broker,replace(self.cfg,trading_mode='LIVE'),DAY)
    def test_perm_id_terms_mutation_blocked(self):
        self.enter();self.broker.fill('BUY');self.broker.orders[self.workflow().ref('BUY')]['perm_id']=7
        with self.assertRaisesRegex(RuntimeError,'permId'):self.arm()
    def test_missing_execution_metadata_no_short(self):
        self.enter();self.broker.fill('BUY');self.broker.metadata={}
        with self.assertRaisesRegex(RuntimeError,'proof'):self.arm()
        self.assertEqual(len(self.broker.sent),1)
    def test_unexpected_position_no_entry(self):
        self.broker.positions={'MSFT':BrokerPosition('MSFT',1,100)}
        with self.assertRaises(RuntimeError):self.enter()
        self.assertFalse(self.broker.sent)
    def test_cancelled_entry_stop_no_resend(self):
        self.enter();self.broker.orders[self.workflow().ref('BUY')]['status']='Cancelled'
        with self.assertRaises(RuntimeError):self.arm()
        with self.assertRaises(RuntimeError):self.enter()
        self.assertEqual(len(self.broker.sent),1)
    def test_prior_observed_proofs_survive_history_expiry(self):
        self.enter();self.broker.fill('BUY');self.arm();self.broker.fill('SELL');self.verify()
        self.broker.orders={};self.broker.executions=[];self.broker.metadata={}
        self.assertEqual(self.verify()['MOC'],'PASS')
    def test_missing_offline_fill_history_stops(self):
        self.enter();self.broker.orders={};self.broker.executions=[]
        with self.assertRaises(RuntimeError):self.arm()
    def test_price_or_quantity_changed_no_entry_repeat(self):
        self.enter();self.broker.orders[self.workflow().ref('BUY')]['quantity']=2
        with self.assertRaisesRegex(RuntimeError,'terms'):self.enter()
    def test_closed_before_close_refused(self):
        with self.assertRaises(ValueError):self.workflow('2026-10-09T19:30:00Z').run('verify-close')
    def test_early_close_and_opg_deadline(self):
        with self.assertRaises(ValueError):phase_window('enter',DAY,'2026-10-09T13:26:00Z')
        phase_window('arm-exit','2026-11-27','2026-11-27T16:59:00Z')
        with self.assertRaises(ValueError):phase_window('arm-exit','2026-11-27','2026-11-27T17:01:00Z')
    def test_verify_reports_cancelled_moc_and_held_position(self):
        self.enter();self.broker.fill('BUY');self.arm()
        self.broker.orders[self.workflow().ref('SELL')]['status']='Cancelled'
        r=self.verify()
        self.assertEqual(r['MOC'],'FAIL');self.assertEqual(r['positions'],{'AAPL':1})
        self.assertEqual(r['orders'][1]['broker_status'],'Cancelled')
        self.assertEqual(len(self.broker.sent),2)
    def test_partial_fill_or_wrong_auction_time_blocks_exit(self):
        self.enter();self.broker.fill('BUY')
        self.broker.metadata['fill-BUY']['exchange_time']='20261009 10:00:00 US/Eastern'
        with self.assertRaisesRegex(RuntimeError,'outside'):self.arm()
        self.assertEqual(len(self.broker.sent),1)
    def test_lost_exit_ack_restart_never_duplicates_moc(self):
        self.enter();self.broker.fill('BUY');self.broker.lose_ack=True
        with self.assertRaises(TimeoutError):self.arm()
        self.store.close();self.store=Store(self.path);self.broker.lose_ack=False
        self.assertTrue(self.arm()['idempotent']);self.assertEqual(len(self.broker.sent),2)
    def test_phase_one_after_closed_does_not_reset_state(self):
        self.enter();self.broker.fill('BUY');self.arm();self.broker.fill('SELL');self.verify();self.enter()
        self.assertEqual(self.store.db.execute('SELECT state FROM auction_sessions').fetchone()[0],'CLOSED')
    def test_unknown_fill_even_with_flat_position_blocks_every_action(self):
        self.broker.executions=[BrokerExecution('unknown',888,TICKER,'BUY',1,100,DAY,ACCOUNT)]
        with self.assertRaises(RuntimeError):self.enter()
        self.assertFalse(self.broker.sent)
    def test_crash_before_transmit_reserved_id_remains_uncertain(self):
        self.broker.fail=True
        with self.assertRaises(TimeoutError):self.enter()
        row=self.store.db.execute('SELECT * FROM auction_order_proofs').fetchone()
        self.assertGreater(row['broker_order_id'],0);self.assertIsNone(row['perm_id'])
        self.assertEqual(self.store.intent(row['intent_id'])['status'],'SUBMITTING')
    def test_restart_after_offline_exit_fill_imports_both_executions(self):
        self.enter();self.broker.fill('BUY');self.arm();self.broker.fill('SELL')
        self.store.close();self.store=Store(self.path)
        self.assertEqual(self.verify()['MOC'],'PASS')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM executions').fetchone()[0],2)

    def test_cli_live_and_wrong_account_refused_before_connection(self):
        from bot.auction_checkpoints import main
        for environment in ({'TRADING_MODE':'LIVE','IBKR_ALLOWED_ACCOUNT_ID':ACCOUNT},
                            {'TRADING_MODE':'PAPER','IBKR_ALLOWED_ACCOUNT_ID':'DU_OTHER'}):
            with patch.dict('os.environ',environment), patch('sys.argv',['auction','enter','--session',DAY]), patch('bot.auction_checkpoints.AuctionBroker') as real:
                with self.assertRaises(ValueError):main()
                real.assert_not_called()
    def test_late_entry_never_transmits(self):
        with self.assertRaises(ValueError):self.workflow('2026-10-09T13:26:00Z').run('enter')
        self.assertFalse(self.broker.sent)

    def test_kill_switch_no_send(self):
        self.cfg=replace(self.cfg,trading_enabled=False)
        with self.assertRaises(RuntimeError):self.enter()
        self.assertFalse(self.broker.sent)

if __name__=='__main__':unittest.main()
