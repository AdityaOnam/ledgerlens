"""Work out what price was agreed for a SKU on a given day.

Precedence: the latest amendment effective on or before the day beats its order form. If the
day falls after the order form's term and it auto-renews, the renewal price ceiling is the
last agreed price raised by the uplift cap once per renewal year. Two amendments taking
effect the same day with different prices are a conflict: the code does not pick a winner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ledgerlens.domain.dates import add_months
from ledgerlens.domain.models import Agreement, Evidence
from ledgerlens.domain.money import money


@dataclass
class Resolved:
    status: str  # "agreed" | "renewal" | "conflict" | "unpriced" | "none"
    price: Decimal | None = None
    licensed_qty: int | None = None
    true_up_allowed: bool = False
    renewal_years: int = 0
    base_price: Decimal | None = None
    evidence: list[Evidence] = field(default_factory=list)
    candidates: list[tuple[Decimal, Evidence]] = field(default_factory=list)


def current_term_end(a: Agreement, on: date) -> tuple[date, int]:
    """End of the term that contains `on`, and how many renewals that took (0 = original)."""
    end, years = a.end, 0
    while a.auto_renew and on > end:
        end, years = add_months(end, 12), years + 1
    return end, years


def resolve(agreements: list[Agreement], vendor: str, sku: str, on: date) -> Resolved:
    bases = [a for a in agreements if a.vendor == vendor and a.amends is None and a.term_for(sku)]
    live = []
    for a in bases:
        end, years = current_term_end(a, on)
        if a.start <= on <= end:
            live.append((a, years))
    if not live:
        return Resolved("none")
    base, years = max(live, key=lambda t: t[0].start)
    term = base.term_for(sku)
    assert term is not None

    amendments = [a for a in agreements if a.amends == base.agreement_id and a.term_for(sku)
                  and a.effective is not None and a.effective <= on]
    price, qty, evidence = term.unit_price, term.licensed_qty, [term.evidence]
    if amendments:
        latest = max(a.effective for a in amendments)  # type: ignore[type-var]
        same_day = [a for a in amendments if a.effective == latest]
        prices = {a.term_for(sku).unit_price for a in same_day}  # type: ignore[union-attr]
        if len(prices) > 1:
            cands = [(a.term_for(sku).unit_price, a.term_for(sku).evidence)  # type: ignore[union-attr]
                     for a in same_day]
            return Resolved("conflict", licensed_qty=qty, candidates=cands,
                            true_up_allowed=base.true_up_allowed)
        amended = same_day[0].term_for(sku)
        assert amended is not None
        price, qty, evidence = amended.unit_price, amended.licensed_qty, [amended.evidence]

    if years == 0:
        return Resolved("agreed", price, qty, base.true_up_allowed, 0, price, evidence)
    if base.uplift_cap is None:
        # Renewed with no cap: any renewal price is allowed; seat limits still hold.
        return Resolved("unpriced", None, qty, base.true_up_allowed, years, price, evidence)
    ceiling = price
    for _ in range(years):
        ceiling = money(ceiling * (1 + base.uplift_cap))
    cap_line = Evidence(base.evidence.doc_id, f"Renewal uplift cap: {(base.uplift_cap * 100).normalize():f}%")
    return Resolved("renewal", ceiling, qty, base.true_up_allowed, years, price,
                    [*evidence, cap_line])
