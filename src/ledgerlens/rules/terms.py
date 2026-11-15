"""Work out what price was agreed for a SKU on a given day, and from which source.

Three kinds of source can state a price, in order of precedence:

1. a signed amendment, from its effective date;
2. the signed order form it amends, for the order form's term (and renewals);
3. an email in which the vendor and the customer agree a price.

The governing term is the highest-precedence one in force; among amendments the latest effective
date wins. An email that took effect on or before the governing term is superseded by it. An
email that takes effect later and states a different price is neither applied nor ignored:
it is a conflict for a person, because the email may record a deal that was never papered, or a
promise the signed terms do not honour. Two amendments taking effect the same day with different
prices are a conflict too. Only where no signed document prices the SKU does an agreed email
price govern on its own.

With an ``Authority``, only agreements signed by a listed signatory and emails agreed by a listed
address bind. The others are returned as ``unauthorised`` so the detectors can say when an
invoice relies on one, instead of disputing a price a colleague may in fact have agreed.

If the day falls after the order form's term and it auto-renews, the renewal price ceiling is the
last agreed price raised by the uplift cap once per renewal year.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from ledgerlens.domain.dates import add_months
from ledgerlens.domain.models import Agreement, Evidence, PriceStatement
from ledgerlens.domain.money import money
from ledgerlens.rules.authority import Authority

AMENDMENT, ORDER_FORM, EMAIL = "amendment", "order form", "email"
PRECEDENCE = {AMENDMENT: 3, ORDER_FORM: 2, EMAIL: 1}

SAME_DAY_AMENDMENTS = "same_day_amendments_disagree"
LATER_EMAIL = "later_email_disagrees_with_signed_terms"
SAME_DAY_EMAILS = "same_day_emails_disagree"


@dataclass(frozen=True)
class Term:
    """One source's statement of a SKU's price (and, for agreements, its licensed quantity)."""

    source: str  # AMENDMENT | ORDER_FORM | EMAIL
    ref: str  # agreement id, or the email's document id
    price: Decimal
    qty: int | None
    effective: date
    party: str  # who signed (agreements) or agreed (emails) on the customer's side
    evidence: Evidence

    @property
    def label(self) -> str:
        if self.source == EMAIL:
            return f"email of {self.effective} agreed by {self.party or 'unknown'}"
        return f"{self.source} {self.ref}"


@dataclass
class Resolved:
    status: str  # "agreed" | "renewal" | "conflict" | "unpriced" | "none"
    price: Decimal | None = None
    licensed_qty: int | None = None
    true_up_allowed: bool = False
    renewal_years: int = 0
    base_price: Decimal | None = None
    evidence: list[Evidence] = field(default_factory=list)
    candidates: list[Term] = field(default_factory=list)
    reason: str = ""  # why a conflict is a conflict
    unauthorised: list[Term] = field(default_factory=list)


def current_term_end(a: Agreement, on: date) -> tuple[date, int]:
    """End of the term that contains `on`, and how many renewals that took (0 = original)."""
    end, years = a.end, 0
    while a.auto_renew and on > end:
        end, years = add_months(end, 12), years + 1
    return end, years


def _agreement_term(a: Agreement, sku: str) -> Term:
    t = a.term_for(sku)
    assert t is not None
    source, effective = (ORDER_FORM, a.start) if a.amends is None else (AMENDMENT, a.effective)
    assert effective is not None
    return Term(source, a.agreement_id, t.unit_price, t.licensed_qty, effective, a.signed_by,
                t.evidence)  # fmt: skip


def _email_term(p: PriceStatement) -> Term:
    return Term(EMAIL, p.evidence.doc_id, p.unit_price, None, p.effective, p.agreed_by, p.evidence)


def _in_force(a: Agreement, on: date) -> bool:
    if a.amends is not None:
        return a.effective is not None and a.effective <= on
    end, _ = current_term_end(a, on)
    return a.start <= on <= end


def _latest(terms: list[Term]) -> list[Term]:
    """The terms with the latest effective date (several if they share it)."""
    last = max(t.effective for t in terms)
    return [t for t in terms if t.effective == last]


def _disagree(terms: list[Term]) -> bool:
    return len({t.price for t in terms}) > 1


def resolve(
    agreements: list[Agreement],
    vendor: str,
    sku: str,
    on: date,
    statements: Iterable[PriceStatement] = (),
    authority: Authority | None = None,
) -> Resolved:
    docs = [a for a in agreements if a.vendor == vendor and a.term_for(sku) and _in_force(a, on)]
    emails = [
        _email_term(p)
        for p in statements
        if p.vendor == vendor and p.sku == sku and p.effective <= on
    ]

    def binds(t: Term) -> bool:
        if authority is None:
            return True
        return authority.may_agree(t.party) if t.source == EMAIL else authority.may_sign(t.party)

    signed = [a for a in docs if binds(_agreement_term(a, sku))]
    agreed = [t for t in emails if binds(t)]
    unauthorised = [
        *(_agreement_term(a, sku) for a in docs if a not in signed),
        *(t for t in emails if not binds(t)),
    ]

    bases = [a for a in signed if a.amends is None]
    if not bases:
        if not agreed:
            return Resolved("none", unauthorised=unauthorised)
        latest = _latest(agreed)
        if _disagree(latest):
            return Resolved(
                "conflict", candidates=latest, reason=SAME_DAY_EMAILS, unauthorised=unauthorised
            )
        t = latest[0]
        return Resolved("agreed", t.price, None, False, 0, t.price, [t.evidence],
                        unauthorised=unauthorised)  # fmt: skip

    base = max(bases, key=lambda a: a.start)
    _, years = current_term_end(base, on)
    governing = _agreement_term(base, sku)
    amendments = [_agreement_term(a, sku) for a in signed if a.amends == base.agreement_id]
    if amendments:
        latest = _latest(amendments)
        if _disagree(latest):
            return Resolved(
                "conflict",
                licensed_qty=governing.qty,
                true_up_allowed=base.true_up_allowed,
                candidates=latest,
                reason=SAME_DAY_AMENDMENTS,
                unauthorised=unauthorised,
            )
        governing = latest[0]

    price, qty, evidence = governing.price, governing.qty, [governing.evidence]
    status: str = "agreed"
    ceiling: Decimal | None = price
    if years and base.uplift_cap is None:
        status, ceiling = "unpriced", None  # renewed with no cap: seat limits still hold
    elif years and base.uplift_cap is not None:
        status, raised = "renewal", price
        for _ in range(years):
            raised = money(raised * (1 + base.uplift_cap))
        ceiling = raised
        cap = f"Renewal uplift cap: {(base.uplift_cap * 100).normalize():f}%"
        evidence = [*evidence, Evidence(base.evidence.doc_id, cap)]

    later = [t for t in agreed if t.effective > governing.effective]
    if later:
        latest = _latest(later)
        if ceiling is None and not _disagree(latest):
            t = latest[0]  # an uncapped renewal sets no price, so the agreed email does
            return Resolved("agreed", t.price, qty, base.true_up_allowed, years, price,
                            [t.evidence], unauthorised=unauthorised)  # fmt: skip
        if ceiling is None or {t.price for t in latest} != {ceiling}:
            signed_term = replace(governing, price=ceiling if ceiling is not None else price)
            return Resolved(
                "conflict",
                licensed_qty=qty,
                true_up_allowed=base.true_up_allowed,
                candidates=[signed_term, *latest],
                reason=LATER_EMAIL,
                unauthorised=unauthorised,
            )

    return Resolved(status, ceiling, qty, base.true_up_allowed, years, price, evidence,
                    unauthorised=unauthorised)  # fmt: skip
