from datetime import date
from decimal import Decimal

import pytest

from ledgerlens.domain.dates import add_months, parse_date
from ledgerlens.domain.money import money, percent


def test_money_parses_symbols_and_rounds_half_up():
    assert money("$1,234.505") == Decimal("1234.51")
    assert money(38) == Decimal("38.00")


def test_money_rejects_text():
    with pytest.raises(ValueError):
        money("n/a")


def test_percent():
    assert percent("7%") == Decimal("0.07")


@pytest.mark.parametrize("text", ["2026-03-01", "1 March 2026", "March 1, 2026", "1 Mar 2026."])
def test_parse_date_formats(text):
    assert parse_date(text) == date(2026, 3, 1)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
