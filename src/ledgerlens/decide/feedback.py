"""A reviewer's answers to findings, and how they apply to the findings of later batches.

Three answers, each one-off or standing:

- ``dismiss``: not a problem. The finding is closed with no action.
- ``approve``: go ahead with the proposed action. An approved finding skips the review
  threshold, and an approved conflict becomes a dispute down to the lowest price stated.
- ``price``: for a conflict only, the price that governs. Applied by the rules, so a later
  invoice is priced against it (and disputed if it bills more) instead of escalating again.

A one-off answer covers that exact finding. A standing answer also covers later findings of the
same class, vendor, SKU and rule worth no more than ``up_to`` (by default, the amount of the
finding answered), so a standing "dismiss" can never quietly swallow a bigger leak. Standing
approvals are not accepted for renewal notices or conflicts: a notice is a decision for each
renewal, and a conflict is settled by naming the price.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from ledgerlens.domain.models import (
    Answer,
    Decision,
    Finding,
    FindingClass,
    FindingRecord,
    Scope,
)
from ledgerlens.domain.money import money

NO_STANDING_APPROVAL = {str(FindingClass.CONFLICT), str(FindingClass.RENEWAL_NOTICE_DUE)}


class FeedbackError(ValueError):
    """An answer that does not make sense for the finding it is given to."""


def record(finding: Finding, batch: str) -> FindingRecord:
    candidates = tuple(Decimal(c) for c in finding.details.get("candidates", ()))
    return FindingRecord(
        finding.id,
        finding.key,
        str(finding.cls),
        finding.vendor,
        finding.invoice_id,
        finding.sku,
        finding.rule,
        finding.amount,
        finding.summary,
        batch,
        candidates,
    )


def answer(
    rec: FindingRecord,
    ans: Answer,
    scope: Scope,
    reviewer: str,
    on: date,
    *,
    price: Decimal | None = None,
    up_to: Decimal | None = None,
    note: str = "",
) -> Decision:
    """Turn a reviewer's answer into a Decision, refusing answers that do not fit."""
    if not reviewer.strip():
        raise FeedbackError("say who decided (reviewer name)")
    if ans is Answer.PRICE:
        if rec.cls != FindingClass.CONFLICT:
            raise FeedbackError(f"a price can only settle a conflict, not {rec.cls}")
        if price is None:
            raise FeedbackError("name the price that governs")
        price = money(price)
        if price not in rec.candidates:
            options = ", ".join(f"${c}" for c in rec.candidates)
            raise FeedbackError(f"${price} is not one of the prices in conflict ({options})")
    elif price is not None:
        raise FeedbackError(f"a price goes with the 'price' answer, not '{ans}'")
    if scope is Scope.STANDING and ans is Answer.APPROVE and rec.cls in NO_STANDING_APPROVAL:
        raise FeedbackError(f"{rec.cls} cannot be approved standing; answer each one")
    if up_to is not None and scope is not Scope.STANDING:
        raise FeedbackError("an amount limit only applies to a standing decision")
    if scope is Scope.STANDING and ans is not Answer.PRICE:
        up_to = money(up_to if up_to is not None else rec.amount)
    return Decision(
        rec.id,
        rec.key,
        ans,
        scope,
        reviewer.strip(),
        on,
        rec.cls,
        rec.vendor,
        rec.sku,
        rec.rule,
        price=price,
        up_to=up_to,
        note=note,
    )


def revoke(decisions: list[Decision], finding_id: str, on: date) -> list[Decision]:
    """Stop every active decision made on ``finding_id`` from applying; the history stays."""
    hits = [d for d in decisions if d.finding_id == finding_id and d.active]
    if not hits:
        raise FeedbackError(f"no active decision on finding {finding_id}")
    return [replace(d, revoked_on=on) if d in hits else d for d in decisions]


def _same_kind(d: Decision, f: Finding) -> bool:
    return (d.cls, d.vendor, d.sku, d.rule) == (str(f.cls), f.vendor, f.sku, f.rule)


@dataclass
class Applied:
    decision: Decision | None = None
    note: str = ""  # why a standing decision that looked relevant did not apply


def lookup(finding: Finding, decisions: Iterable[Decision]) -> Applied:
    """The decision that governs a new finding, if any. The latest decision wins.

    Price decisions are not returned: the rules have already used them."""
    usable = [d for d in decisions if d.active and d.answer is not Answer.PRICE]
    for d in reversed(usable):
        if d.key == finding.key:
            return Applied(d)
    for d in reversed(usable):
        if not (d.standing and _same_kind(d, finding)):
            continue
        if d.up_to is not None and finding.amount > d.up_to:
            return Applied(
                note=f"{finding.id}: standing {d.answer} from finding {d.finding_id} "
                f"({d.reviewer}) covers up to ${d.up_to}; this one is ${finding.amount}, "
                "so it is reported as usual"
            )
        return Applied(d)
    return Applied()


def rulings(decisions: Iterable[Decision]) -> list[Decision]:
    """Active price decisions, for the rules to settle conflicts with."""
    return [d for d in decisions if d.active and d.answer is Answer.PRICE]
