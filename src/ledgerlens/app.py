"""Run a mailbox batch by batch: read, remember, detect, apply decisions, decide, report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledgerlens.decide import feedback
from ledgerlens.decide.policy import DEFAULT_REVIEW_THRESHOLD, Mode, decide
from ledgerlens.domain.models import Answer, Decision, Finding, Scope
from ledgerlens.ingest.convert import OCR
from ledgerlens.ingest.extract import Extractor, extract
from ledgerlens.ingest.mailbox import read_mailbox
from ledgerlens.rules.authority import Authority
from ledgerlens.rules.detectors import detect
from ledgerlens.store import decisions as decision_log
from ledgerlens.store.memory import Memory

MEMORY_FILE = "memory.json"


@dataclass
class BatchResult:
    batch: str
    as_of: date
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    closed: list[Finding] = field(default_factory=list)  # dismissed by a reviewer's decision


def run(
    mailbox: Path,
    state_dir: Path,
    mode: Mode = Mode.SUPERVISED,
    threshold: Decimal = DEFAULT_REVIEW_THRESHOLD,
    as_of: date | None = None,
    extractor: Extractor = extract,
    ocr: OCR | None = None,
    authority: Authority | None = None,
) -> list[BatchResult]:
    """Process every batch not yet in memory. Findings already reported are not repeated.

    ``extractor`` turns documents into facts: the layout reader by default, or an LLM-backed
    one. Detectors and the policy are the same either way. ``ocr`` reads scanned PDFs and
    image attachments; without it they are skipped with a note. ``authority`` lists who may
    agree terms; without it every signed or emailed term binds. Reviewers' decisions recorded
    in the state directory (see ``answer``) are applied to every new finding."""
    path = state_dir / MEMORY_FILE
    mem = Memory.load(path)
    decisions = decision_log.load(state_dir / decision_log.FILENAME)
    rulings = feedback.rulings(decisions)
    results = []
    for batch in read_mailbox(mailbox, ocr):
        if batch.name in mem.batches:
            continue
        x = extractor(batch.documents, mem.vendor_domains)
        mem.absorb(batch.name, x)
        day = as_of or batch.as_of or date.today()
        result = BatchResult(batch.name, day, notes=[*batch.skipped, *x.unread])
        for finding in detect(mem, day, authority, rulings):
            if finding.key in mem.reported:
                continue
            mem.reported[finding.key] = batch.name
            mem.findings[finding.id] = feedback.record(finding, batch.name)
            applied = feedback.lookup(finding, decisions)
            if applied.note:
                result.notes.append(applied.note)
            d = applied.decision
            if d is not None and d.answer is Answer.DISMISS:
                finding.details["dismissed_by"] = _cite(d)
                result.closed.append(finding)
                continue
            if d is not None and d.answer is Answer.APPROVE:
                finding.details["approved_by"] = _cite(d)
            result.findings.append(decide(finding, mode, threshold))
        results.append(result)
        mem.save(path)
    return results


def _cite(d: Decision) -> str:
    return f"{d.label()} (finding {d.finding_id})"


def answer(
    state_dir: Path,
    finding_id: str,
    ans: Answer,
    scope: Scope,
    reviewer: str,
    on: date | None = None,
    *,
    price: Decimal | None = None,
    up_to: Decimal | None = None,
    note: str = "",
) -> Decision:
    """Record a reviewer's answer to a reported finding. It applies from the next audit on.

    Raises KeyError for an unknown finding id and FeedbackError for an answer that does not fit."""
    rec = Memory.load(state_dir / MEMORY_FILE).findings.get(finding_id)
    if rec is None:
        raise KeyError(finding_id)
    d = feedback.answer(
        rec, ans, scope, reviewer, on or date.today(), price=price, up_to=up_to, note=note
    )
    path = state_dir / decision_log.FILENAME
    decision_log.save(path, [*decision_log.load(path), d])
    return d


def revoke(state_dir: Path, finding_id: str, on: date | None = None) -> list[Decision]:
    """Withdraw the active decisions on a finding; returns the decision log as saved."""
    path = state_dir / decision_log.FILENAME
    updated = feedback.revoke(decision_log.load(path), finding_id, on or date.today())
    decision_log.save(path, updated)
    return updated
