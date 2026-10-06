"""Currency-specific cash; never converts BASE or account aggregates into USD."""
from datetime import datetime,timezone
import math
from zoneinfo import ZoneInfo


def numeric(value):
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and abs(value)<1e100 else None


def settled_on(schedule,day):
    """Latest known settlement balance on/before day; future settlement is excluded."""
    rows={}
    try:
        for item in schedule.split(';'):
            date,value=item.split(':')
            datetime.strptime(date,'%Y%m%d')
            balance=numeric(value)
            if balance is None or date in rows:return None
            rows[date]=balance
    except (ValueError,AttributeError):return None
    eligible=[date for date in rows if date<=day.replace('-','')]
    return rows[max(eligible)] if eligible else None


def currency_cash(values,day=None):
    day=day or datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    cash={};settled={};available={};verified={}
    currencies={currency for key,currency in values if currency not in ('BASE','')}
    for currency in sorted(currencies):
        def ledger(tag):
            candidates=[values[(key,currency)] for key in ('$LEDGER-'+tag,tag) if (key,currency) in values]
            parsed=[numeric(v) for v in candidates]
            if not parsed or any(v is None for v in parsed):return None
            return min(parsed)
        balance=ledger('CashBalance')
        total=ledger('TotalCashBalance')
        if total is None and any((key,currency) in values for key in ('$LEDGER-TotalCashBalance','TotalCashBalance')):
            balance=None
        if balance is not None:
            cash[currency]=min(balance,total) if total is not None else balance
        settled_value=ledger('SettledCash')
        invalid_settlement=settled_value is None and any((key,currency) in values
            for key in ('SettledCash','$LEDGER-SettledCash'))
        schedules=[values[(key,currency)] for key in ('SettledCashByDate','$LEDGER-SettledCashByDate')
                   if (key,currency) in values]
        if schedules:
            parsed=[settled_on(schedule,day) for schedule in schedules]
            scheduled=min(parsed) if all(value is not None for value in parsed) else None
            invalid_settlement=invalid_settlement or scheduled is None
            # An invalid/unavailable schedule cannot be bypassed with aggregate funds.
            settled_value=scheduled if settled_value is None else (
                min(settled_value,scheduled) if scheduled is not None else None)
        if settled_value is not None:settled[currency]=settled_value
        funds=numeric(values.get(('AvailableFunds',currency)))
        if funds is not None:available[currency]=funds
        limits=[cash[currency]] if currency in cash else []
        if settled_value is not None:limits.append(settled_value)
        if funds is not None:limits.append(funds)
        evidence=(not invalid_settlement and (settled_value is not None or
                  (not schedules and funds is not None)))
        if ('AvailableFunds',currency) in values and funds is None:evidence=False
        if limits and currency in cash and evidence:
            verified[currency]=max(0.,min(limits))
    return cash,available,settled,verified
