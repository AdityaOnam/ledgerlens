"""One detector per finding class. Each reads facts from Memory and returns Findings.

Line checks run in a fixed order and stop at the first that explains the whole line, so one
dollar is never claimed twice: cancelled > duplicate > no agreement > relies on an unauthorised
term > not priced > conflict > cites a missing document > price > seats.

A conflict a reviewer has settled by naming the price (a ``price`` decision) is priced at that
price instead, with the reviewer's ruling cited as evidence; see ``decide.feedback``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from ledgerlens.domain.models import (
    Decision,
    DocumentReference,
    Evidence,
    Finding,
    FindingClass,
    Invoice,
    InvoiceLine,
)
from ledgerlens.domain.money import money
from ledgerlens.rules.authority import Authority
from ledgerlens.rules.terms import (
    EMAIL,
    SAME_DAY_AMENDMENTS,
    Resolved,
    Term,
    current_term_end,
    resolve,
)
from ledgerlens.store.memory import Memory

CREDIT_GRACE_DAYS = 60
RENEWAL_LOOKAHEAD_DAYS = 45

C = FindingClass


def _period(line: InvoiceLine) -> str:
    return f"{line.period_start.isoformat()}..{line.period_end.isoformat()}"


def _finding(
    cls: FindingClass,
    inv: Invoice,
    line: InvoiceLine,
    amount: Decimal,
    summary: str,
    rule: str,
    evidence: list,
    **details,
) -> Finding:
    return Finding(
        cls,
        inv.vendor,
        summary,
        money(amount),
        [line.evidence, *evidence],
        invoice_id=inv.invoice_id,
        sku=line.sku,
        rule=rule,
        details={"period": _period(line), **details},
    )


def _over(line: InvoiceLine, r: Resolved) -> Decimal:
    """How much of a line the binding terms do not cover: price above the agreed price plus
    seats above the licence (unless true-up is allowed). Everything, if nothing binds."""
    qty = line.qty
    if r.licensed_qty is not None and not r.true_up_allowed:
        qty = min(qty, r.licensed_qty)
    unit = line.unit_price if r.price is None else min(line.unit_price, r.price)
    if r.status == "none":
        unit, qty = Decimal(0), 0
    return money(line.unit_price * line.qty - unit * qty)


def _relies_on(line: InvoiceLine, t: Term, r: Resolved) -> bool:
    """True if a line follows an unauthorised term where it departs from the binding ones."""
    price = t.price == line.unit_price and (r.price is None or line.unit_price > r.price)
    seats = (
        t.qty is not None
        and r.licensed_qty is not None
        and not r.true_up_allowed
        and r.licensed_qty < line.qty <= t.qty
    )
    return (price or seats) and _over(line, r) > 0


def _conflict_summary(sku: str, r: Resolved) -> str:
    if r.reason == SAME_DAY_AMENDMENTS:
        return f"Agreements effective the same day disagree on {sku}: " + " vs ".join(
            f"${t.price}" for t in r.candidates
        )
    return f"Sources disagree on the price of {sku}: " + " vs ".join(
        f"{t.label} says ${t.price}" for t in r.candidates
    )


def _missing_documents(mem: Memory, vendor: str) -> list[DocumentReference]:
    """Order forms and amendments a vendor's documents cite that are not on file."""
    have = {a.agreement_id for a in mem.agreements}
    return [x for x in mem.references if x.vendor == vendor and x.ref not in have]


def _ruling(rulings: list[Decision], conflict: Finding, prices: set[Decimal]) -> Decision | None:
    """The latest price decision that settles this conflict: one made on this very finding, or
    a standing one for the vendor and SKU that names one of the prices now in conflict."""
    for d in reversed(rulings):
        same_line = (d.vendor, d.sku) == (conflict.vendor, conflict.sku)
        if d.key == conflict.key or (d.standing and same_line and d.price in prices):
            return d
    return None


def _settled(r: Resolved, d: Decision) -> Resolved:
    assert d.price is not None
    chosen = next((t for t in r.candidates if t.price == d.price), None)
    ruling = Evidence(
        f"decision:{d.finding_id}",
        f"{d.reviewer} ruled on {d.decided_on} that ${d.price} governs {d.sku}"
        + (f" ({d.note})" if d.note else ""),
    )
    evidence = [*([chosen.evidence] if chosen else []), ruling]
    return Resolved("agreed", d.price, r.licensed_qty, r.true_up_allowed, 0, d.price, evidence,
                    unauthorised=r.unauthorised)  # fmt: skip


def _ordered(invoices: list[Invoice]) -> list[Invoice]:
    return sorted(invoices, key=lambda i: (i.issued, i.invoice_id))


def check_lines(
    mem: Memory, authority: Authority | None = None, rulings: list[Decision] | None = None
) -> Iterator[Finding]:
    billed_before: dict[tuple[str, str, date, date], Invoice] = {}
    unknown_vendor_reported: set[str] = set()
    for inv in _ordered(mem.invoices):
        has_agreement = any(a.vendor == inv.vendor for a in mem.agreements)
        for line in inv.lines:
            slot = (inv.vendor, line.sku, line.period_start, line.period_end)
            earlier = billed_before.get(slot)
            billed_before.setdefault(slot, inv)

            cancel = next(
                (
                    c
                    for c in mem.cancellations
                    if c.vendor == inv.vendor
                    and c.sku == line.sku
                    and c.effective <= line.period_start
                ),
                None,
            )
            if cancel:
                yield _finding(
                    C.BILLED_AFTER_CANCEL,
                    inv,
                    line,
                    line.amount,
                    f"{line.sku} billed for {_period(line)} after cancellation "
                    f"effective {cancel.effective}",
                    "cancelled_sku_billed",
                    [cancel.evidence],
                    requested_by=cancel.requested_by,
                )
                continue
            if earlier is not None and earlier.invoice_id != inv.invoice_id:
                yield _finding(
                    C.DUPLICATE_CHARGE,
                    inv,
                    line,
                    line.amount,
                    f"{line.sku} for {_period(line)} already billed on {earlier.invoice_id}",
                    "same_sku_same_period",
                    [earlier.evidence],
                    first_invoice=earlier.invoice_id,
                )
                continue

            if not has_agreement:
                if inv.invoice_id in unknown_vendor_reported:
                    continue
                unknown_vendor_reported.add(inv.invoice_id)
                refs = [r for r in mem.references if r.vendor == inv.vendor]
                missing = refs[0] if refs else None
                yield Finding(
                    C.CANNOT_DETERMINE,
                    inv.vendor,
                    f"No agreement on file for {inv.vendor}; "
                    + (
                        f"{missing.kind} {missing.ref} is cited but was never received"
                        if missing
                        else "no order form has been received"
                    ),
                    inv.total,
                    [inv.evidence, *([missing.evidence] if missing else [])],
                    invoice_id=inv.invoice_id,
                    rule="no_agreement",
                    details={
                        "missing": missing.ref if missing else "order form",
                        "holder": missing.holder if missing else inv.vendor,
                        "ref": missing.ref if missing else "",
                    },
                )
                continue

            r = resolve(
                mem.agreements, inv.vendor, line.sku, line.period_start, mem.prices, authority
            )
            relied_on = next((t for t in r.unauthorised if _relies_on(line, t, r)), None)
            if relied_on and r.status != "conflict":
                signed = relied_on.source != EMAIL
                yield _finding(
                    C.CANNOT_DETERMINE,
                    inv,
                    line,
                    _over(line, r),
                    f"{line.sku} billed at ${line.unit_price} x {line.qty} as in "
                    f"{relied_on.label}, which {relied_on.party or 'nobody'} "
                    f"{'signed' if signed else 'agreed'} without authority to agree terms",
                    "term_agreed_without_authority",
                    [relied_on.evidence, *r.evidence],
                    missing=f"sign-off on {relied_on.label} by an authorised signatory",
                    holder=authority.contact if authority else "",
                    ref=relied_on.ref,
                    agreed_by=relied_on.party,
                )
                continue
            if r.status == "none":
                yield _finding(
                    C.CANNOT_DETERMINE,
                    inv,
                    line,
                    line.amount,
                    f"{line.sku} is not priced in any {inv.vendor} agreement for {_period(line)}",
                    "sku_not_in_agreement",
                    [],
                    missing="price term for " + line.sku,
                    holder=inv.vendor,
                )
                continue
            ruled: Decision | None = None
            if r.status == "conflict":
                low = min(t.price for t in r.candidates)
                conflict = _finding(
                    C.CONFLICT,
                    inv,
                    line,
                    (line.unit_price - low) * line.qty,
                    _conflict_summary(line.sku, r),
                    r.reason,
                    [t.evidence for t in r.candidates],
                    candidates=[str(t.price) for t in r.candidates],
                    sources=[t.label for t in r.candidates],
                )
                ruled = _ruling(rulings or [], conflict, {t.price for t in r.candidates})
                if ruled is None:
                    if line.unit_price > low:
                        yield conflict
                    continue
                r = _settled(r, ruled)
            missing = _missing_documents(mem, inv.vendor)
            if missing and _over(line, r) > 0:
                ref = missing[0]
                yield _finding(
                    C.CANNOT_DETERMINE,
                    inv,
                    line,
                    _over(line, r),
                    f"{line.sku} billed at ${line.unit_price} x {line.qty}, more than the terms "
                    f"on file allow; {ref.kind} {ref.ref} is cited but was never received and "
                    "may change them",
                    "cited_document_missing",
                    [*r.evidence, ref.evidence],
                    missing=ref.ref,
                    holder=ref.holder,
                    ref=ref.ref,
                )
                continue

            if r.price is not None and line.unit_price > r.price:
                if r.status == "renewal":
                    yield _finding(
                        C.UPLIFT_OVER_CAP,
                        inv,
                        line,
                        (line.unit_price - r.price) * line.qty,
                        f"{line.sku} renewed at ${line.unit_price}; cap allows "
                        f"${r.price} (from ${r.base_price})",
                        "renewal_uplift_cap",
                        r.evidence,
                        allowed=str(r.price),
                    )
                else:
                    basis, rule, extra = f"agreed ${r.price}", "unit_price_above_agreed", {}
                    if ruled:
                        basis = f"ruled ${r.price} by {ruled.reviewer}"
                        rule, extra = "unit_price_above_ruled", {"ruling": ruled.finding_id}
                    yield _finding(
                        C.PRICE_OVER_CONTRACT,
                        inv,
                        line,
                        (line.unit_price - r.price) * line.qty,
                        f"{line.sku} billed at ${line.unit_price}, {basis}",
                        rule,
                        r.evidence,
                        allowed=str(r.price),
                        **extra,
                    )
            if r.licensed_qty is not None and line.qty > r.licensed_qty and not r.true_up_allowed:
                unit = min(line.unit_price, r.price) if r.price is not None else line.unit_price
                extra = line.qty - r.licensed_qty
                yield _finding(
                    C.SEATS_OVER_LICENSED,
                    inv,
                    line,
                    unit * extra,
                    f"{line.qty} {line.sku} billed, {r.licensed_qty} licensed and "
                    "true-up not permitted",
                    "qty_above_licensed_no_true_up",
                    r.evidence,
                    licensed=r.licensed_qty,
                )


def check_credits(mem: Memory, as_of: date) -> Iterator[Finding]:
    applied = {c.ref for inv in mem.invoices for c in inv.credits}
    for promise in mem.credits:
        due_by = promise.promised_on + timedelta(days=CREDIT_GRACE_DAYS)
        if promise.ref in applied or as_of < due_by:
            continue
        later = [
            i for i in mem.invoices if i.vendor == promise.vendor and i.issued > promise.promised_on
        ]
        yield Finding(
            C.CREDIT_NOT_APPLIED,
            promise.vendor,
            f"Credit {promise.ref} of ${promise.amount} promised {promise.promised_on}"
            f" is missing from {len(later)} later invoice(s)",
            promise.amount,
            [promise.evidence, *[i.evidence for i in later]],
            rule="promised_credit_missing",
            details={"ref": promise.ref, "due_by": due_by.isoformat()},
        )


def check_renewals(mem: Memory, as_of: date) -> Iterator[Finding]:
    horizon = as_of + timedelta(days=RENEWAL_LOOKAHEAD_DAYS)
    for a in mem.agreements:
        if a.amends is not None or not a.auto_renew or a.notice_days <= 0:
            continue
        end, _ = current_term_end(a, as_of)
        deadline = end - timedelta(days=a.notice_days)
        if not as_of <= deadline <= horizon:
            continue
        cancelled = {
            c.sku for c in mem.cancellations if c.vendor == a.vendor and c.effective <= end
        }
        monthly = sum(
            (p.unit_price * p.licensed_qty for p in a.prices if p.sku not in cancelled), Decimal(0)
        )
        yield Finding(
            C.RENEWAL_NOTICE_DUE,
            a.vendor,
            f"{a.agreement_id} auto-renews {end + timedelta(days=1)}; notice is due by "
            f"{deadline} ({(deadline - as_of).days} days)",
            monthly * 12,
            [a.evidence],
            rule="auto_renew_notice_window",
            details={
                "ref": a.agreement_id,
                "deadline": deadline.isoformat(),
                "term_end": end.isoformat(),
            },
        )


def check_totals(mem: Memory) -> Iterator[Finding]:
    """Completeness: the lines and credits read from an invoice must add up to its printed total.

    When they do not, either a line was missed in reading (a scan, a page break) or the vendor's
    arithmetic is wrong. The code cannot tell which, so it says so and a person looks; the gap
    itself is the amount at stake. Line checks still run on the lines that were read."""
    for inv in _ordered(mem.invoices):
        gap = inv.total - inv.computed_total
        if gap == 0:
            continue
        direction = "more" if gap > 0 else "less"
        yield Finding(
            C.CANNOT_DETERMINE,
            inv.vendor,
            f"{inv.invoice_id} prints a total of ${inv.total}, ${abs(gap)} {direction} than its "
            f"lines and credits (${inv.computed_total}); a line may be missing from the reading "
            "or the total may be wrong",
            money(abs(gap)),
            [inv.evidence, *([inv.total_evidence] if inv.total_evidence else [])],
            invoice_id=inv.invoice_id,
            rule="printed_total_mismatch",
            details={
                "ref": "total",
                "printed_total": str(inv.total),
                "computed_total": str(inv.computed_total),
                "missing": f"complete copy of {inv.invoice_id}",
                "holder": inv.vendor,
            },
        )


def detect(
    mem: Memory,
    as_of: date,
    authority: Authority | None = None,
    rulings: list[Decision] | None = None,
) -> list[Finding]:
    """Every finding the facts in memory support. ``rulings`` are reviewers' price decisions."""
    return [
        *check_lines(mem, authority, rulings),
        *check_totals(mem),
        *check_credits(mem, as_of),
        *check_renewals(mem, as_of),
    ]
