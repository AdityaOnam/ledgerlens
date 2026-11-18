"""Typed facts extracted from documents, and the findings derived from them.

Every fact carries Evidence: the document it came from and the verbatim line that says it.
Rules only ever read facts, never raw text, so each finding can cite its sources.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Evidence:
    doc_id: str
    quote: str

    def to_dict(self) -> dict[str, str]:
        return {"doc_id": self.doc_id, "quote": self.quote}


@dataclass(frozen=True)
class PriceTerm:
    sku: str
    description: str
    unit_price: Decimal
    licensed_qty: int
    evidence: Evidence


@dataclass(frozen=True)
class Agreement:
    """An order form or signed amendment with one vendor."""

    agreement_id: str
    vendor: str
    start: date
    end: date
    auto_renew: bool
    notice_days: int
    uplift_cap: Decimal | None
    true_up_allowed: bool
    prices: tuple[PriceTerm, ...]
    evidence: Evidence
    amends: str | None = None
    effective: date | None = None
    signed_by: str = ""  # the customer's signatory as printed, e.g. "Priya Raman, VP Finance"

    def term_for(self, sku: str) -> PriceTerm | None:
        return next((p for p in self.prices if p.sku == sku), None)


@dataclass(frozen=True)
class Cancellation:
    vendor: str
    sku: str
    effective: date
    requested_by: str
    evidence: Evidence


@dataclass(frozen=True)
class PriceStatement:
    """A unit price agreed in an email rather than in a signed document.

    ``agreed_by`` is the customer-side address on the email: the sender if the customer wrote
    it, otherwise the customer recipient the vendor was writing to."""

    vendor: str
    sku: str
    unit_price: Decimal
    effective: date
    agreed_by: str
    evidence: Evidence


@dataclass(frozen=True)
class CreditPromise:
    vendor: str
    ref: str
    amount: Decimal
    promised_on: date
    evidence: Evidence


@dataclass(frozen=True)
class DocumentReference:
    """A document that another document cites, e.g. 'per order form OF-2026-044'."""

    vendor: str
    ref: str
    kind: str
    holder: str
    evidence: Evidence


@dataclass(frozen=True)
class InvoiceLine:
    sku: str
    description: str
    period_start: date
    period_end: date
    qty: int
    unit_price: Decimal
    amount: Decimal
    evidence: Evidence


@dataclass(frozen=True)
class AppliedCredit:
    ref: str
    amount: Decimal
    evidence: Evidence


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    vendor: str
    issued: date
    due: date
    lines: tuple[InvoiceLine, ...]
    credits: tuple[AppliedCredit, ...]
    total: Decimal
    evidence: Evidence
    total_evidence: Evidence | None = None  # the line that prints the total, when there is one

    @property
    def computed_total(self) -> Decimal:
        """What the lines and applied credits add up to (credits are stored as positive)."""
        return sum((x.amount for x in self.lines), Decimal(0)) - sum(
            (c.amount for c in self.credits), Decimal(0)
        )


class FindingClass(StrEnum):
    PRICE_OVER_CONTRACT = "price_over_contract"
    SEATS_OVER_LICENSED = "seats_over_licensed"
    UPLIFT_OVER_CAP = "uplift_over_cap"
    BILLED_AFTER_CANCEL = "billed_after_cancel"
    DUPLICATE_CHARGE = "duplicate_charge"
    CREDIT_NOT_APPLIED = "credit_not_applied"
    RENEWAL_NOTICE_DUE = "renewal_notice_due"
    CONFLICT = "conflict"
    CANNOT_DETERMINE = "cannot_determine"


class Action(StrEnum):
    DISPUTE = "dispute"
    REQUEST_CREDIT = "request_credit"
    SEND_NOTICE = "send_notice"
    REQUEST_DOCUMENT = "request_document"
    HUMAN_REVIEW = "human_review"


@dataclass
class Finding:
    cls: FindingClass
    vendor: str
    summary: str
    amount: Decimal
    evidence: list[Evidence]
    invoice_id: str | None = None
    sku: str | None = None
    rule: str = ""
    action: Action | None = None
    executed: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable identity, so the same problem found in two batches is reported once."""
        return "|".join(
            str(x)
            for x in (
                self.cls,
                self.vendor,
                self.invoice_id or "",
                self.sku or "",
                self.details.get("period", ""),
                self.details.get("ref", ""),
            )
        )

    @property
    def id(self) -> str:
        """Short handle for the key, used by reviewers to answer a finding."""
        return hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:8]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cls"] = str(self.cls)
        d["amount"] = str(self.amount)
        d["action"] = str(self.action) if self.action else None
        d["key"] = self.key
        d["id"] = self.id
        return d


@dataclass(frozen=True)
class FindingRecord:
    """What is remembered about a reported finding, so a reviewer can answer it later."""

    id: str
    key: str
    cls: str
    vendor: str
    invoice_id: str | None
    sku: str | None
    rule: str
    amount: Decimal
    summary: str
    batch: str
    candidates: tuple[Decimal, ...] = ()  # the prices a conflict is between


class Answer(StrEnum):
    DISMISS = "dismiss"  # not a problem: close it, take no action
    APPROVE = "approve"  # go ahead with the proposed action
    PRICE = "price"  # a conflict: this price governs


class Scope(StrEnum):
    ONCE = "once"  # this finding only
    STANDING = "standing"  # this finding and later ones of the same kind


@dataclass(frozen=True)
class Decision:
    """A reviewer's answer to a finding. Kept forever; a revoked decision stops applying.

    A one-off decision applies to the finding with ``key`` (which reappears only if the mailbox
    is audited again from scratch). A standing one also applies to later findings with the same
    class, vendor, SKU and rule, as long as they are worth no more than ``up_to``."""

    finding_id: str
    key: str
    answer: Answer
    scope: Scope
    reviewer: str
    decided_on: date
    cls: str
    vendor: str
    sku: str | None
    rule: str
    price: Decimal | None = None
    up_to: Decimal | None = None
    note: str = ""
    revoked_on: date | None = None

    @property
    def active(self) -> bool:
        return self.revoked_on is None

    @property
    def standing(self) -> bool:
        return self.scope is Scope.STANDING

    def label(self) -> str:
        return f"{self.scope} {self.answer} by {self.reviewer} on {self.decided_on}"
