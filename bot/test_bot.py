"""Offline tests only: every broker is a fake, never an IBKR connection."""
from dataclasses import replace
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

import pandas as pd

from bot.calendar import before_moc_cutoff,exit_session,next_session
from bot.broker_ibkr import IBKRPaperBroker
from bot.config import ROOT,Settings
from bot.models import BrokerExecution,BrokerOrder,BrokerPosition,BrokerSnapshot,Signal
from bot.portfolio import entry_intent
from bot.runtime import ReconciliationRequired,run_daily,run_exits,synchronize
from bot.storage import Store
from bot.strategy import FrozenSwingV2


class FakeStrategy:
    strategy_id='2366a81673c5'
    def __init__(self,signals):self.signals=signals
    def generate_signals(self,frame,asof):return self.signals


class FakeData:
    def load(self,asof):return pd.DataFrame({'asof':[asof]})


class FakeBroker:
    def __init__(self,account='DU12345',cash=10000):
        self.account=account;self.cash=cash;self.positions={};self.open_orders=[];self.executions=[];self.sent=[]
    def snapshot(self,account_id):
        if account_id!=self.account:raise ValueError('wrong account')
        return BrokerSnapshot(account_id,self.cash,dict(self.positions),tuple(self.open_orders),tuple(self.executions))
    def submit(self,intent):
        if intent.account_id!=self.account:raise ValueError('wrong account')
        order_id=100+len(self.sent);self.sent.append(intent)
        self.open_orders.append(BrokerOrder(order_id,intent.intent_id,intent.ticker,intent.side,
                                            intent.quantity,'Submitted',self.account))
        return order_id
    def close(self):pass


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'bot.sqlite')
        self.settings=Settings(trading_mode='PAPER',trading_enabled=True,allowed_account_id='DU12345')
        self.broker=FakeBroker()
        self.signal=Signal('2366a81673c5','AAPL','2026-10-01','2026-10-02',
                           exit_session('2026-10-02',9),100.,'frozen rules',9)
    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_session_entry_exit_weekend_holiday(self):
        self.assertEqual(next_session('2026-11-25'),'2026-11-27')
        self.assertEqual(next_session('2026-11-27'),'2026-11-30')
        self.assertEqual(exit_session('2026-10-02',9),'2026-10-14')
        self.assertNotEqual(exit_session('2026-10-02',9),'2026-10-11')
        self.assertTrue(before_moc_cutoff('2026-10-14','2026-10-14T19:00:00Z'))
        self.assertFalse(before_moc_cutoff('2026-10-14','2026-10-14T19:01:00Z'))
        self.assertTrue(before_moc_cutoff('2026-11-27','2026-11-27T16:59:00Z'))
        self.assertFalse(before_moc_cutoff('2026-11-27','2026-11-27T17:01:00Z'))

    def test_frozen_strategy_no_future_and_source(self):
        strategy=FrozenSwingV2()
        self.assertEqual(strategy.strategy_id,'2366a81673c5')
        self.assertEqual(strategy.candidate['horizon'],9)
        self.assertEqual(strategy.required_data()['warmup_sessions'],100)
        dates=pd.bdate_range('2025-01-01','2026-10-01')
        frame=pd.DataFrame([dict(Date=d,Ticker=t,Open=100.,High=101.,Low=99.,Close=100.,Volume=1000)
                            for t in ('AAPL','SPY') for d in dates])
        with self.assertRaisesRegex(ValueError,'Future'):
            strategy.generate_signals(frame,'2026-09-30')
        self.assertEqual(strategy.generate_signals(frame,'2026-10-01'),[])

    def test_kill_switch_and_live_rejected(self):
        with self.assertRaises(ValueError):replace(self.settings,trading_mode='LIVE').validate()
        with self.assertRaises(ValueError):replace(self.settings,allowed_account_id='U12345').validate()
        with self.assertRaises(ValueError):replace(self.settings,ibkr_port=7496).validate()
        result=run_daily(self.store,replace(self.settings,trading_enabled=False),FakeStrategy([self.signal]),FakeData(),
                         asof='2026-10-01',at_utc='2026-10-01T22:00:00Z')
        self.assertEqual(result['orders_sent'],0)
        self.assertEqual(result['reasons']['KILL_SWITCH'],1)
        self.assertEqual(len(self.broker.sent),0)

    def test_missed_next_open_rejects_late_entry(self):
        with self.assertRaisesRegex(ValueError,'deadline missed'):
            run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,
                      asof='2026-10-01',at_utc='2026-10-02T14:00:00Z')
        self.assertEqual(len(self.broker.sent),0)

    def test_risk_limits_and_simultaneous_signals(self):
        snapshot=self.broker.snapshot('DU12345')
        intent,reason=entry_intent(self.signal,self.store,snapshot,self.settings)
        self.assertIsNone(reason);self.assertEqual(intent.order_type,'LOO')
        self.assertLessEqual(intent.quantity*intent.limit_price,1000.)
        self.store.save_intent(intent,'PLANNED')
        _,reason=entry_intent(self.signal,self.store,snapshot,self.settings)
        self.assertEqual(reason,'ALREADY_HELD_OR_PENDING')
        self.store.save_intent(replace(intent,intent_id='other-1',ticker='MSFT'),'PLANNED')
        self.store.save_intent(replace(intent,intent_id='other-2',ticker='NVDA'),'PLANNED')
        self.store.save_intent(replace(intent,intent_id='other-3',ticker='AMZN'),'PLANNED')
        self.store.save_intent(replace(intent,intent_id='other-4',ticker='META'),'PLANNED')
        other=replace(self.signal,ticker='JPM')
        _,reason=entry_intent(other,self.store,snapshot,self.settings)
        self.assertIn(reason,('MAX_POSITIONS','MAX_ORDERS_PER_DAY'))

    def test_total_exposure_and_account_guard(self):
        occupied={f'X{i}':BrokerPosition(f'X{i}',10,1000.) for i in range(5)}
        snapshot=BrokerSnapshot('DU12345',10000.,occupied)
        _,reason=entry_intent(self.signal,self.store,snapshot,replace(self.settings,max_positions=10))
        self.assertEqual(reason,'CASH_OR_EXPOSURE_LIMIT')
        intent,_=entry_intent(self.signal,self.store,self.broker.snapshot('DU12345'),self.settings)
        adapter=IBKRPaperBroker(self.settings)
        with self.assertRaisesRegex(ValueError,'Paper account'):
            adapter.submit(replace(intent,account_id='U-PERSONAL'))

    def test_submission_idempotent_after_restart(self):
        kwargs=dict(asof='2026-10-01',at_utc='2026-10-01T22:00:00Z')
        first=run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,**kwargs)
        self.assertEqual(first['orders_sent'],1)
        self.assertEqual(len(self.broker.sent),1)
        # A new process can reopen the same SQLite ledger and see the order.
        self.store.close();self.store=Store(Path(self.temp.name)/'bot.sqlite')
        second=run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,**kwargs)
        self.assertEqual(second['orders_sent'],0)
        self.assertEqual(len(self.broker.sent),1)

    def test_restart_resumes_only_never_submitted_plan(self):
        intent,_=entry_intent(self.signal,self.store,self.broker.snapshot('DU12345'),self.settings)
        self.store.save_intent(intent,'PLANNED')
        self.store.close();self.store=Store(Path(self.temp.name)/'bot.sqlite')
        result=run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,
                         asof='2026-10-01',at_utc='2026-10-01T22:00:00Z')
        self.assertEqual(result['orders_sent'],1)
        self.assertEqual(len(self.broker.sent),1)

    def test_ambiguous_crash_and_reconciliation_divergence(self):
        intent,_=entry_intent(self.signal,self.store,self.broker.snapshot('DU12345'),self.settings)
        self.store.save_intent(intent,'PLANNED');self.assertTrue(self.store.order_claim(intent.intent_id,'DU12345'))
        with self.assertRaisesRegex(ReconciliationRequired,'ambiguous submission'):
            synchronize(self.store,self.broker,'DU12345')
        self.store.close();self.store=Store(Path(self.temp.name)/'bot.sqlite')
        with self.assertRaises(ReconciliationRequired):synchronize(self.store,self.broker,'DU12345')

    def test_fill_reconciliation_and_ninth_session_exit(self):
        kwargs=dict(asof='2026-10-01',at_utc='2026-10-01T22:00:00Z')
        run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,**kwargs)
        order=self.broker.open_orders.pop()
        self.broker.executions=[BrokerExecution('exec-1',order.broker_order_id,'AAPL','BUY',order.quantity,100.,
                                                '2026-10-02','DU12345')]
        self.broker.positions={'AAPL':BrokerPosition('AAPL',order.quantity,order.quantity*100.)}
        synchronize(self.store,self.broker,'DU12345')
        pos=self.store.position('DU12345','AAPL')
        self.assertEqual(pos['entry_session'],'2026-10-02')
        self.assertEqual(pos['exit_session'],'2026-10-14')
        exit_result=run_exits(self.store,self.settings,self.broker,today='2026-10-14',at_utc='2026-10-14T19:00:00Z')
        self.assertEqual(exit_result['orders_sent'],1)
        self.assertEqual(self.broker.sent[-1].order_type,'MOC')
        self.assertEqual(self.broker.sent[-1].quantity,order.quantity)
        second=run_exits(self.store,self.settings,self.broker,today='2026-10-14',at_utc='2026-10-14T19:00:00Z')
        self.assertEqual(second['orders_sent'],0)
        self.assertEqual(len(self.broker.sent),2)
        exit_order=self.broker.open_orders.pop()
        self.broker.executions.append(BrokerExecution('exec-exit',exit_order.broker_order_id,'AAPL','SELL',
                                                      order.quantity,110.,'2026-10-14','DU12345'))
        self.broker.positions={}
        synchronize(self.store,self.broker,'DU12345')
        self.assertIsNone(self.store.position('DU12345','AAPL'))

    def test_fill_price_vs_raw_open_recorded(self):
        run_daily(self.store,self.settings,FakeStrategy([self.signal]),FakeData(),self.broker,
                  asof='2026-10-01',at_utc='2026-10-01T22:00:00Z')
        order=self.broker.open_orders.pop()
        self.broker.executions=[BrokerExecution('exec-open',order.broker_order_id,'AAPL','BUY',order.quantity,
                                                101.,'2026-10-02','DU12345')]
        self.broker.positions={'AAPL':BrokerPosition('AAPL',order.quantity,order.quantity*101.)}
        synchronize(self.store,self.broker,'DU12345')
        self.store.record_benchmark('exec-open',100.,'OPEN')
        row=self.store.db.execute('SELECT benchmark_price,fill_deviation_bps FROM executions').fetchone()
        self.assertEqual(row['benchmark_price'],100.)
        self.assertAlmostEqual(row['fill_deviation_bps'],100.)

    def test_unknown_open_order_blocks(self):
        self.broker.open_orders.append(BrokerOrder(55,'unowned','AAPL','BUY',1,'Submitted','DU12345'))
        with self.assertRaisesRegex(ReconciliationRequired,'unknown broker order'):
            synchronize(self.store,self.broker,'DU12345')

    def test_concurrent_runs_are_rejected(self):
        other=Store(Path(self.temp.name)/'bot.sqlite')
        try:
            active=self.store.run_start('daily','PAPER','2026-10-01')
            with self.assertRaisesRegex(RuntimeError,'Another bot run'):
                other.run_start('daily','PAPER','2026-10-01')
            self.store.run_end(active,'OK')
            resumed=other.run_start('daily','PAPER','2026-10-01')
            other.run_end(resumed,'OK')
        finally:other.close()

    def test_unowned_paper_position_blocks_orders(self):
        self.broker.positions={'AAPL':BrokerPosition('AAPL',10,1000.)}
        with self.assertRaisesRegex(ReconciliationRequired,'positions DB'):
            synchronize(self.store,self.broker,'DU12345')

    def test_no_credentials_in_git(self):
        tracked=subprocess.check_output(['git','ls-files','--cached'],cwd=ROOT,text=True).splitlines()
        self.assertFalse(any(Path(f).name.startswith('.env') or f.endswith(('.pem','.key')) for f in tracked))
        for key in ('IBKR_ALLOWED_ACCOUNT_ID','APCA_API_KEY_ID','APCA_API_SECRET_KEY'):
            secret=os.environ.get(key)
            if secret and len(secret)>8:
                self.assertFalse(any(secret in (ROOT/f).read_text(errors='ignore') for f in tracked if (ROOT/f).is_file()))


if __name__=='__main__':unittest.main()
