"""Timestamp regressions; no IBKR connection or trading."""
import unittest

from bot.execution_time import execution_timestamp, timestamp_evidence


class ExecutionTimeTests(unittest.TestCase):
    def test_brisbane_and_eastern_same_instant(self):
        a=execution_timestamp('20261010 05:59:34 Australia/Brisbane')
        b=execution_timestamp('20261009 15:59:34 US/Eastern')
        self.assertEqual(a,b)
        self.assertEqual(a.date().isoformat(),'2026-10-09')
        self.assertEqual(a.tz_convert('UTC').isoformat(),'2026-10-09T19:59:34+00:00')

    def test_raw_timestamp_preserved(self):
        raw='20261010 05:59:34 Australia/Brisbane'
        evidence=timestamp_evidence(raw)
        self.assertEqual(evidence['exchange_time'],raw)
        self.assertEqual(evidence['execution_session'],'2026-10-09')
        self.assertEqual(evidence['execution_time_et'],'2026-10-09T15:59:34-04:00')

    def test_winter_dst_offset(self):
        self.assertEqual(execution_timestamp('20261130 14:30:00 UTC').hour,9)
        self.assertEqual(execution_timestamp('20261009 13:30:00 UTC').hour,9)

    def test_missing_unknown_zone_and_invalid_timestamp_refused(self):
        for raw in ('20261009 16:00:00','20261009 16:00:00 NOT_A_ZONE','invalid','20261309 16:00:00 UTC'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):execution_timestamp(raw)

    def test_ambiguous_dst_refused(self):
        with self.assertRaises(ValueError):execution_timestamp('20261101 01:30:00 America/New_York')

    def test_nonexistent_dst_refused(self):
        with self.assertRaises(ValueError):execution_timestamp('20260308 02:30:00 America/New_York')


if __name__=='__main__':unittest.main()
