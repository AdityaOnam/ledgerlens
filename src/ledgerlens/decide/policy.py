"""Pick an action for each finding, and whether it may run without a person.

Confidence never chooses an action. Only the class, the amount and the mode do:
- supervised: nothing executes; every action is a recommendation.
- autonomous: an action executes only if it is low-risk (dispute, credit request or document
  request), below the review threshold, and not a conflict.
Conflicts and renewal decisions always go to a person.

A finding a reviewer has approved (see ``feedback``) has had its person: it skips the threshold,
and an approved conflict is disputed down to the lowest price stated. Supervised mode still
executes nothing, and a renewal notice is never sent by Ledgerlens itself.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from ledgerlens.domain.models import Action, Finding, FindingClass

DEFAULT_REVIEW_THRESHOLD = Decimal("2500.00")

C = FindingClass

NATURAL_ACTION = {
    C.PRICE_OVER_CONTRACT: Action.DISPUTE,
    C.SEATS_OVER_LICENSED: Action.DISPUTE,
    C.UPLIFT_OVER_CAP: Action.DISPUTE,
    C.BILLED_AFTER_CANCEL: Action.DISPUTE,
    C.DUPLICATE_CHARGE: Action.DISPUTE,
    C.CREDIT_NOT_APPLIED: Action.REQUEST_CREDIT,
    C.RENEWAL_NOTICE_DUE: Action.SEND_NOTICE,
    C.CANNOT_DETERMINE: Action.REQUEST_DOCUMENT,
    C.CONFLICT: Action.HUMAN_REVIEW,
}
SAFE_TO_AUTOMATE = {Action.DISPUTE, Action.REQUEST_CREDIT, Action.REQUEST_DOCUMENT}
# A document request costs nothing even when the invoice behind it is large.
AMOUNT_INDEPENDENT = {Action.REQUEST_DOCUMENT}


class Mode(StrEnum):
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


def decide(finding: Finding, mode: Mode, threshold: Decimal = DEFAULT_REVIEW_THRESHOLD) -> Finding:
    action = NATURAL_ACTION[finding.cls]
    if finding.details.get("approved_by"):
        if finding.cls is C.CONFLICT:
            action = Action.DISPUTE
    elif action not in AMOUNT_INDEPENDENT and finding.amount >= threshold:
        action = Action.HUMAN_REVIEW
    finding.action = action
    finding.executed = mode is Mode.AUTONOMOUS and action in SAFE_TO_AUTOMATE
    return finding
