"""All tests offline: no broker connection or order submission."""
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import pandas as pd

from bot.auction_validation import Audit, AuctionBroker, ACCOUNT, STRATEGY, order_for, safe_limit, schedule, wait_fill, verify_auction_time
from bot.calendar import before_moc_cutoff
from bot.config import Settings
from bot.models import OrderIntent
from bot.runtime import _submit, ReconciliationRequired
from bot.storage import Store


class AuctionTests(unittest.TestCase):
    def intent(self, side='BUY'):
        return OrderIntent('test',STRATEGY,'AAPL',side,1,'2026-10-09','test','time',1,'2026-10-09',
                           'LOO' if side=='BUY' else 'MOC',338.35 if side=='BUY' else None,ACCOUNT,336.67)

    def build(self,intent):
        with patch.dict('sys.modules',{'ibapi.order':SimpleNamespace(Order=SimpleNamespace)}):
            return order_for(intent)

    def test_opg(self):
        o=self.build(self.intent());self.assertEqual((o.orderType,o.tif,o.totalQuantity,o.account),('LMT','OPG',1,ACCOUNT))
        self.assertFalse(o.outsideRth);self.assertTrue(o.transmit)

    def test_moc(self):
        o=self.build(self.intent('SELL'));self.assertEqual((o.orderType,o.tif),('MOC','DAY'))

    def test_no_market_substitution(self):
        with self.assertRaises(ValueError):self.build(replace(self.intent(),order_type='MKT'))

    def test_scope(self):
        for changes in ({'account_id':'U123'},{'quantity':2},{'ticker':'NVDA'},{'strategy_id':'SwingV2'}):
            with self.assertRaises(ValueError):self.build(replace(self.intent(),**changes))

    def test_no_live(self):
        with self.assertRaises(ValueError):Settings(trading_mode='LIVE',allowed_account_id=ACCOUNT).validate()

    def test_safe_limit(self):
        self.assertEqual(safe_limit(336.67),338.35)
        self.assertLess(safe_limit(400,346.619568),346.619568)
        for invalid in (0,float('nan'),float('inf')):
            with self.assertRaises(ValueError):safe_limit(invalid)

    def test_et_normal_and_dst(self):
        opening,closing=schedule('2026-10-09')
        self.assertEqual(str(opening),'2026-10-09 13:30:00+00:00')
        self.assertEqual(closing.tz_convert('America/New_York').hour,16)
        self.assertEqual(schedule('2026-11-30')[0].hour,14)

    def test_early_close_deadline(self):
        opening,closing=schedule('2026-11-27')
        self.assertEqual(closing.tz_convert('America/New_York').hour,13)
        self.assertTrue(before_moc_cutoff('2026-11-27','2026-11-27T16:59:00Z'))
        self.assertFalse(before_moc_cutoff('2026-11-27','2026-11-27T17:01:00Z'))

    def test_logger_timestamp_and_failure(self):
        with tempfile.TemporaryDirectory() as d:
            a=Audit(Path(d)/'audit.jsonl')
            with redirect_stdout(StringIO()):a.emit('CALLBACK',at_utc='explicit',status='Filled')
            self.assertFalse(a.failed)
            self.assertEqual(json.loads(a.path.read_text())['at_utc'],'explicit')
            a.emit('BAD',unserializable=object());self.assertTrue(a.failed)

    def test_duplicate_claim_and_uncertain_submission(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'test.sqlite');i=self.intent();s.save_intent(i,'PLANNED')
            cfg=Settings(allowed_account_id=ACCOUNT,trading_enabled=True)
            calls=[]
            def fail(intent):calls.append(intent);raise TimeoutError('uncertain')
            b=SimpleNamespace(submit=fail)
            with self.assertRaises(TimeoutError):_submit(s,b,i,cfg)
            with self.assertRaises(ReconciliationRequired):_submit(s,b,i,cfg)
            self.assertEqual(len(calls),1);self.assertEqual(s.intent(i.intent_id)['status'],'SUBMITTING');s.close()

    def test_wait_rejected_and_disconnected(self):
        for connected,status in ((True,'Cancelled'),(False,'Submitted')):
            b=SimpleNamespace(app=SimpleNamespace(isConnected=lambda:connected,ack_status={1:status}),
                              thread=SimpleNamespace(is_alive=lambda:True),audit=SimpleNamespace(failed=False),
                              stop_path=Path('/does-not-exist-auction-stop'))
            with self.assertRaises(RuntimeError):wait_fill(b,1,pd.Timestamp.now(tz='UTC')+pd.Timedelta(seconds=1))

    def test_auction_execution_times(self):
        opening, closing = schedule('2026-10-09')
        b=SimpleNamespace(fill_times={1:'20261009 09:30:01 US/Eastern',2:'20261009 16:00:01 US/Eastern'}, audit=SimpleNamespace(emit=lambda *a,**k:None))
        verify_auction_time(b,1,'OPG',opening,opening+pd.Timedelta(minutes=5))
        verify_auction_time(b,2,'MOC',closing,closing+pd.Timedelta(minutes=10))
        with self.assertRaises(RuntimeError):verify_auction_time(b,1,'MOC',closing,closing+pd.Timedelta(minutes=10))

    def test_kill_file(self):
        with tempfile.TemporaryDirectory() as d:
            stop=Path(d)/'stop';stop.touch()
            b=SimpleNamespace(app=SimpleNamespace(isConnected=lambda:True),thread=SimpleNamespace(is_alive=lambda:True),
                              audit=SimpleNamespace(failed=False),stop_path=stop)
            with self.assertRaises(RuntimeError):wait_fill(b,1,pd.Timestamp.now(tz='UTC')+pd.Timedelta(seconds=1))


if __name__=='__main__':unittest.main()
