"""A synthetic customer's dealings with its vendors, as plain data.

The generator (``synth``) invents a World and writes it out as a mailbox. The oracle
(``oracle``) works out from the World alone what an audit must find. The oracle never reads the
mailbox and never uses Ledgerlens' readers or rules, so a bug on either side shows up as a
disagreement instead of agreeing with itself.

Everything here is invented: companies, people, products, prices and dates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Person:
    name: str
    title: str
    email: str

    @property
    def address(self) -> str:
        return f"{self.name} <{self.email}>"

    @property
    def signature(self) -> str:
        return f"{self.name}, {self.title}"


@dataclass(frozen=True)
class Sku:
    code: str
    description: str
    price: Decimal  # per unit per month
    licensed: int


@dataclass(frozen=True)
class Contract:
    """A signed order form. Amendments and emailed prices are not generated (yet)."""

    ref: str
    start: date
    end: date
    auto_renew: bool
    notice_days: int
    true_up: bool
    uplift_cap: str | None
    skus: tuple[Sku, ...]
    sent: date

    def sku(self, code: str) -> Sku | None:
        return next((s for s in self.skus if s.code == code), None)


@dataclass(frozen=True)
class Line:
    sku: str
    description: str
    start: date
    end: date
    qty: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return cents(self.unit_price * self.qty)


@dataclass
class Bill:
    """One invoice as the vendor sends it. ``total_error`` is added to the printed total."""

    invoice_id: str
    issued: date
    sent: date
    lines: list[Line]
    credits: list[tuple[str, Decimal]] = field(default_factory=list)  # (ref, positive amount)
    total_error: Decimal = Decimal(0)
    corrected_copy: bool = False

    @property
    def computed_total(self) -> Decimal:
        return sum((x.amount for x in self.lines), Decimal(0)) - sum(
            (a for _, a in self.credits), Decimal(0)
        )

    @property
    def printed_total(self) -> Decimal:
        return cents(self.computed_total + self.total_error)


@dataclass(frozen=True)
class Cancel:
    sku: str
    effective: date
    sent: date


@dataclass(frozen=True)
class Credit:
    ref: str
    amount: Decimal
    sent: date  # the day the vendor promised it


@dataclass
class Vendor:
    name: str
    code: str
    domain: str
    printed: bool  # invoices printed as text (like a PDF) rather than CSV
    contract: Contract | None
    bills: list[Bill] = field(default_factory=list)
    cancels: list[Cancel] = field(default_factory=list)
    credits: list[Credit] = field(default_factory=list)

    @property
    def contact(self) -> str:
        return f"accounts@{self.domain}"


@dataclass
class World:
    seed: int
    company: str
    domain: str
    signer: Person
    ap: Person
    vendors: list[Vendor]
    cutoffs: list[date]  # the last day of each batch, which is also the batch's as-of date

    def batch_name(self, index: int) -> str:
        return f"batch_{index + 1:02d}"

    def batch_of(self, sent: date) -> int:
        """Index of the batch a document sent on ``sent`` belongs to."""
        for i, cutoff in enumerate(self.cutoffs):
            if sent <= cutoff:
                return i
        raise ValueError(f"{sent} is after the last batch ({self.cutoffs[-1]})")
