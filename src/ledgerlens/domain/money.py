"""Money as Decimal, always rounded to cents with banker-free half-up rounding."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def money(value: str | int | float | Decimal) -> Decimal:
    """Parse '$1,234.50', '1234.5' or a number into a cent-rounded Decimal."""
    if isinstance(value, Decimal):
        d = value
    else:
        text = str(value).strip().replace("$", "").replace(",", "").replace("USD", "").strip()
        try:
            d = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"not a money amount: {value!r}") from exc
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def percent(value: str | Decimal) -> Decimal:
    """Parse '7%' or '7' into Decimal('0.07')."""
    text = str(value).strip().rstrip("%").strip()
    try:
        return Decimal(text) / Decimal(100)
    except InvalidOperation as exc:
        raise ValueError(f"not a percentage: {value!r}") from exc
