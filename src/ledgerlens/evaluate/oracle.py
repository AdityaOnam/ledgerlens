"""What an audit of a synthetic World must find, worked out from the World alone.

The oracle is written from the rules as the README states them, not from the detectors' code,
and it reads the World the generator built, never the mailbox. It imports nothing from
Ledgerlens but the World itself (a test checks this), so a reading bug, a rule bug or an
oracle bug each shows up as a disagreement.

It replays the mailbox batch by batch, as an audit does: at each batch's as-of date it knows
only the documents sent by then, and a problem is expected once, in the first batch where the
documents on hand prove it.

Rules, as documented:

- Each invoice line is checked in order and the first explanation wins: billed after its
  cancellation took effect (the whole line); billed again for a period an earlier invoice
  already billed (the whole line); from a vendor with no order form (the invoice's printed total,
  once per invoice); then price above the order form ((billed - agreed) x qty) and, separately,
  seats above the licence when true-up is not permitted (extra seats x the lower of the billed
  and the agreed price).
- An invoice whose lines minus applied credits differ from its printed total cannot be
  determined (the gap).
- A promised credit not applied on any invoice 60 days after the promise is missing.
- An auto-renewing order form whose notice deadline falls within 45 days of the as-of date is
  due a decision, worth twelve months of its licensed SKUs not cancelled by the term's end.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import partial

from ledgerlens.evaluate.world import Bill, Cancel, Contract, Vendor, World, cents

CREDIT_GRACE_DAYS = 60
RENEWAL_LOOKAHEAD_DAYS = 45


@dataclass(frozen=True)
class Expected:
    cls: str
    vendor: str
    invoice_id: str | None
    sku: str | None
    ref: str  # credit ref, order form ref, "total" for a total mismatch, otherwise ""
    amount: Decimal
    why: str
    batch: str

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (self.cls, self.vendor, self.invoice_id or "", self.sku or "", self.ref)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "cls": self.cls,
            "vendor": self.vendor,
            "invoice_id": self.invoice_id,
            "sku": self.sku,
            "ref": self.ref,
            "amount": str(self.amount),
            "why": self.why,
            "batch": self.batch,
        }


def expected(world: World) -> list[Expected]:
    """Every finding the World's mailbox must produce, each in the batch that first proves it."""
    out: dict[tuple[str, str, str, str, str], Expected] = {}
    for i, as_of in enumerate(world.cutoffs):
        for e in _at(world, as_of, world.batch_name(i)):
            out.setdefault(e.key, e)
    return list(out.values())


def _at(world: World, as_of: date, batch: str) -> Iterator[Expected]:
    applied = {
        ref for v in world.vendors for b in v.bills if b.sent <= as_of for ref, _ in b.credits
    }
    for v in world.vendors:
        bills = sorted(
            (b for b in v.bills if b.sent <= as_of), key=lambda b: (b.issued, b.invoice_id)
        )
        cancels = [c for c in v.cancels if c.sent <= as_of]
        contract = v.contract if v.contract is not None and v.contract.sent <= as_of else None
        yield from _lines(v, contract, bills, cancels, batch)
        yield from _totals(v, bills, batch)
        yield from _credits(v, applied, as_of, batch)
        if contract is not None:
            yield from _renewal(v, contract, cancels, as_of, batch)


def _lines(
    v: Vendor, contract: Contract | None, bills: list[Bill], cancels: list[Cancel], batch: str
) -> Iterator[Expected]:
    first_billed: dict[tuple[str, date, date], str] = {}
    for b in bills:
        flagged_unknown = False
        for x in b.lines:
            earlier = first_billed.setdefault((x.sku, x.start, x.end), b.invoice_id)
            cancel = next((c for c in cancels if c.sku == x.sku and c.effective <= x.start), None)
            line = partial(_line, v.name, b.invoice_id, x.sku, batch)
            if cancel is not None:
                yield line("billed_after_cancel", x.amount, f"cancelled from {cancel.effective}")
                continue
            if earlier != b.invoice_id:
                yield line("duplicate_charge", x.amount, f"already billed on {earlier}")
                continue
            if contract is None:
                if not flagged_unknown:
                    flagged_unknown = True
                    yield Expected("cannot_determine", v.name, b.invoice_id, None, "",
                                   b.printed_total, "no order form on file", batch)  # fmt: skip
                continue
            sku = contract.sku(x.sku)
            if sku is None:  # never generated; kept so the oracle covers the rule
                yield line("cannot_determine", x.amount, "SKU not in the order form")
                continue
            if x.unit_price > sku.price:
                yield line(
                    "price_over_contract",
                    (x.unit_price - sku.price) * x.qty,
                    f"billed {x.unit_price}, agreed {sku.price}",
                )
            if x.qty > sku.licensed and not contract.true_up:
                yield line(
                    "seats_over_licensed",
                    min(x.unit_price, sku.price) * (x.qty - sku.licensed),
                    f"{x.qty} billed, {sku.licensed} licensed, no true-up",
                )


def _line(
    vendor: str, invoice_id: str, sku: str, batch: str, cls: str, amount: Decimal, why: str
) -> Expected:
    return Expected(cls, vendor, invoice_id, sku, "", cents(amount), why, batch)


def _totals(v: Vendor, bills: list[Bill], batch: str) -> Iterator[Expected]:
    for b in bills:
        gap = b.printed_total - b.computed_total
        if gap:
            yield Expected("cannot_determine", v.name, b.invoice_id, None, "total", abs(gap),
                           f"printed {b.printed_total}, lines add up to {b.computed_total}",
                           batch)  # fmt: skip


def _credits(v: Vendor, applied: set[str], as_of: date, batch: str) -> Iterator[Expected]:
    for c in v.credits:
        due = c.sent + timedelta(days=CREDIT_GRACE_DAYS)
        if c.sent <= as_of and c.ref not in applied and as_of >= due:
            yield Expected("credit_not_applied", v.name, None, None, c.ref, c.amount,
                           f"promised {c.sent}, not applied by {due}", batch)  # fmt: skip


def _next_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)


def _renewal(
    v: Vendor, c: Contract, cancels: list[Cancel], as_of: date, batch: str
) -> Iterator[Expected]:
    if not c.auto_renew or c.notice_days <= 0:
        return
    end = c.end
    while as_of > end:
        end = _next_year(end)
    deadline = end - timedelta(days=c.notice_days)
    if not as_of <= deadline <= as_of + timedelta(days=RENEWAL_LOOKAHEAD_DAYS):
        return
    gone = {x.sku for x in cancels if x.effective <= end}
    monthly = sum((s.price * s.licensed for s in c.skus if s.code not in gone), Decimal(0))
    yield Expected("renewal_notice_due", v.name, None, None, c.ref, cents(monthly * 12),
                   f"renews {end + timedelta(days=1)}, notice due {deadline}", batch)  # fmt: skip
