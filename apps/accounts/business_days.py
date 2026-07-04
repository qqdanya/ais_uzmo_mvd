from datetime import date, datetime, timedelta


def as_date(value):
    """Normalize date/datetime values to date objects."""
    if isinstance(value, datetime):
        return value.date()
    return value


def business_days_inclusive(start, end):
    """Return Mon-Fri days in the inclusive [start, end] interval.

    The request intake day is included. If an unusual interval contains only
    weekend dates, return 1 so the UI never shows a zero-day processing term.
    """
    start = as_date(start)
    end = as_date(end)
    if not start or not end:
        return None
    if end < start:
        return 1

    total_days = (end - start).days + 1
    full_weeks, remainder = divmod(total_days, 7)
    business_days = full_weeks * 5
    start_weekday = start.weekday()

    for offset in range(remainder):
        if (start_weekday + offset) % 7 < 5:
            business_days += 1

    return max(business_days, 1)


def subtract_business_days_inclusive(end, business_days):
    """Return the earliest date whose inclusive business-day distance to end
    is at least ``business_days``.

    Example: with end on Monday and business_days=2, the result is previous
    Friday because Friday + Monday are two working days.
    """
    if business_days <= 1:
        return as_date(end)

    current = as_date(end)
    counted = 1 if current.weekday() < 5 else 0
    while counted < business_days:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            counted += 1
    return current
