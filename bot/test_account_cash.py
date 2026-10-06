"""Offline currency/settlement guard tests; no broker or credentials."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from bot.account_cash import currency_cash,settled_on
from bot.config import Settings
from bot.models import BrokerSnapshot,Signal
from bot.paper_order_test import require_usd_cash
from bot.portfolio import entry_intent
from bot.storage import Store


class CurrencyCashTests(unittest.TestCase):
    def snapshot(self,base,usd=None,settled=None):
        values={('NetLiquidation',base):'1000000',('AvailableFunds',base):'1000000',
                ('$LEDGER-CashBalance','EUR'):'1000000'}
        if usd is not None:values[('$LEDGER-CashBalance','USD')]=str(usd)
        if settled is not None:values[('SettledCash','USD')]=str(settled)
        cash,funds,settled_values,verified=currency_cash(values,'2026-10-06')
        return BrokerSnapshot('DU12345',verified.get('USD',0.),account_currency=base,
            cash_by_currency=cash,available_cash_by_currency=funds,
            settled_cash_by_currency=settled_values,verified_cash_by_currency=verified)

    def test_eur_base_with_verified_usd_is_potentially_authorizable(self):
        snapshot=self.snapshot('EUR',1000,900)
        self.assertEqual(snapshot.available_cash,900)
        require_usd_cash(snapshot)

    def test_zero_usd_refused(self):
        with self.assertRaises(ValueError):require_usd_cash(self.snapshot('EUR',0,0))

    def test_usd_base_with_actual_cash_and_available_funds(self):
        snapshot=self.snapshot('USD',1000)
        self.assertEqual(snapshot.available_cash,1000)
        require_usd_cash(snapshot)

    def test_eur_is_never_used_as_usd(self):
        snapshot=self.snapshot('EUR')
        self.assertEqual(snapshot.available_cash,0)
        self.assertNotIn('USD',snapshot.cash_by_currency)
        with self.assertRaises(ValueError):require_usd_cash(snapshot)

    def test_usd_balance_without_availability_or_settlement_is_refused(self):
        snapshot=self.snapshot('EUR',1000)
        self.assertEqual(snapshot.cash_by_currency['USD'],1000)
        with self.assertRaises(ValueError):require_usd_cash(snapshot)

    def test_prefixed_and_legacy_cash_keys_and_base_are_distinct(self):
        cash,_,_,verified=currency_cash({('$LEDGER-CashBalance','USD'):'123',
            ('$LEDGER-TotalCashBalance','USD'):'120',('SettledCash','USD'):'110',
            ('CashBalance','EUR'):'456',('CashBalance','BASE'):'999999',
            ('AvailableFunds','EUR'):'400'},'2026-10-06')
        self.assertEqual(cash,{'EUR':456.,'USD':120.})
        self.assertEqual(verified,{'EUR':400.,'USD':110.})

    def test_future_settlement_does_not_authorize_today(self):
        values={('$LEDGER-CashBalance','USD'):'1125796.35',
                ('SettledCashByDate','USD'):'20261005:0;20261007:1125796.35'}
        self.assertEqual(currency_cash(values,'2026-10-06')[3]['USD'],0)
        self.assertEqual(currency_cash(values,'2026-10-07')[3]['USD'],1125796.35)

    def test_malformed_or_future_only_settlement_refused(self):
        for schedule in ('bad','20261007:1000','20261005:nan','20261005:1;20261005:2'):
            values={('CashBalance','USD'):'1000',('AvailableFunds','USD'):'1000',
                    ('SettledCashByDate','USD'):schedule}
            self.assertNotIn('USD',currency_cash(values,'2026-10-06')[3])

    def test_nonfinite_cash_and_buying_power_never_authorize(self):
        for value in ('nan','inf','1.7976931348623157e308','bad'):
            self.assertNotIn('USD',currency_cash({('CashBalance','USD'):value,
                ('AvailableFunds','USD'):'1000',('BuyingPower','USD'):'1000000'})[3])

    def test_invalid_present_limits_are_not_ignored(self):
        for tag in ('TotalCashBalance','SettledCash','AvailableFunds'):
            values={('CashBalance','USD'):'1000',('AvailableFunds','USD'):'1000',
                    ('SettledCash','USD'):'1000',(tag,'USD'):'invalid'}
            self.assertNotIn('USD',currency_cash(values)[3])

    def test_notional_plus_buffer_and_missing_verified_usd(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'test.sqlite')
            try:
                settings=Settings(trading_mode='PAPER',trading_enabled=True,allowed_account_id='DU12345')
                signal=Signal('TEST','AAPL','2026-10-05','2026-10-06','2026-10-06',100.,'test',1)
                insufficient=self.snapshot('EUR',107,107)
                self.assertEqual(entry_intent(signal,store,insufficient,settings)[1],'CASH_OR_EXPOSURE_LIMIT')
                sufficient=self.snapshot('EUR',109,109)
                intent,reason=entry_intent(signal,store,sufficient,settings)
                self.assertIsNone(reason)
                self.assertLessEqual(intent.quantity*intent.limit_price+settings.cash_buffer_usd,109)
                absent=replace(sufficient,verified_cash_by_currency={})
                self.assertEqual(entry_intent(signal,store,absent,settings)[1],'USD_CASH_UNVERIFIED_OR_UNAVAILABLE')
            finally:store.close()

    def test_live_account_and_small_buffer_remain_blocked(self):
        for settings in (Settings(trading_mode='LIVE'),Settings(allowed_account_id='U123'),
                         Settings(cash_buffer_usd=0)):
            with self.assertRaises(ValueError):settings.validate()


if __name__=='__main__':unittest.main()
