"""Explicit-zone IBKR execution timestamps; session dates are New York dates."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def execution_timestamp(raw):
    parts = str(raw).split()
    if len(parts) != 3:
        raise ValueError('Execution timestamp requires an explicit timezone: ' + str(raw))
    try:
        ZoneInfo(parts[2])  # Reject unknown/implicit zones; never use host timezone.
        naive = datetime.strptime(' '.join(parts[:2]), '%Y%m%d %H:%M:%S')
        stamp = pd.Timestamp(naive).tz_localize(parts[2], ambiguous='raise', nonexistent='raise')
        return stamp.tz_convert('America/New_York')
    except Exception as exc:
        raise ValueError('Invalid or ambiguous execution timestamp: ' + str(raw)) from exc


def timestamp_evidence(raw):
    stamp = execution_timestamp(raw)
    return dict(exchange_time=str(raw),execution_time_et=stamp.isoformat(),
                execution_time_utc=stamp.tz_convert('UTC').isoformat(),
                execution_session=stamp.date().isoformat())
