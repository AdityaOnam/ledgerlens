"""Date helpers. Months are added calendar-style, clamped to the month's last day."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime

_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y")


def parse_date(text: str) -> date:
    t = re.sub(r"\s+", " ", text.strip().rstrip("."))
    for fmt in _FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {text!r}")


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
