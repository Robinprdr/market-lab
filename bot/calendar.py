"""NYSE session arithmetic; all entry/exit counts are market sessions."""
from datetime import datetime, timezone
import pandas as pd
import exchange_calendars as xc


def exchange(day):
    d = pd.Timestamp(day).normalize()
    return xc.get_calendar('XNYS', start=str(d-pd.Timedelta(days=30)), end=str(d+pd.Timedelta(days=90)))


def next_session(day):
    cal = exchange(day)
    previous = cal.date_to_session(pd.Timestamp(day).normalize(),direction='previous')
    return cal.next_session(previous).date().isoformat()


def exit_session(entry_day, holding_sessions=9):
    if holding_sessions < 1:
        raise ValueError('Holding sessions must be positive')
    cal = exchange(entry_day)
    start = cal.date_to_session(pd.Timestamp(entry_day).normalize(),direction='none')
    return cal.session_offset(start,holding_sessions-1).date().isoformat()


def last_complete_session(at_utc=None):
    now = pd.Timestamp(at_utc or datetime.now(timezone.utc)).tz_convert('UTC')
    cal = exchange(now.tz_convert('America/New_York').date())
    completed = cal.schedule[cal.schedule.close <= now]
    if completed.empty:
        raise RuntimeError('No completed NYSE session')
    return completed.index[-1].date().isoformat()


def before_next_open(signal_day,at_utc=None):
    now = pd.Timestamp(at_utc or datetime.now(timezone.utc)).tz_convert('UTC')
    cal = exchange(signal_day)
    nxt = pd.Timestamp(next_session(signal_day))
    return now < cal.schedule.loc[nxt,'open']


def before_moc_cutoff(session,at_utc=None):
    now = pd.Timestamp(at_utc or datetime.now(timezone.utc)).tz_convert('UTC')
    cal = exchange(session)
    day = pd.Timestamp(session)
    if day not in cal.schedule.index:
        return False
    open_time,close_time = cal.schedule.loc[day,['open','close']]
    return open_time <= now <= close_time-pd.Timedelta(minutes=60)
