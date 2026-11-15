"""Run a mailbox batch by batch: read, remember, detect, decide, report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledgerlens.decide.policy import DEFAULT_REVIEW_THRESHOLD, Mode, decide
from ledgerlens.domain.models import Finding
from ledgerlens.ingest.convert import OCR
from ledgerlens.ingest.extract import Extractor, extract
from ledgerlens.ingest.mailbox import read_mailbox
from ledgerlens.rules.authority import Authority
from ledgerlens.rules.detectors import detect
from ledgerlens.store.memory import Memory


@dataclass
class BatchResult:
    batch: str
    as_of: date
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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
    agree terms; without it every signed or emailed term binds."""
    path = state_dir / "memory.json"
    mem = Memory.load(path)
    results = []
    for batch in read_mailbox(mailbox, ocr):
        if batch.name in mem.batches:
            continue
        x = extractor(batch.documents, mem.vendor_domains)
        mem.absorb(batch.name, x)
        day = as_of or batch.as_of or date.today()
        result = BatchResult(batch.name, day, notes=[*batch.skipped, *x.unread])
        for finding in detect(mem, day, authority):
            if finding.key in mem.reported:
                continue
            mem.reported[finding.key] = batch.name
            result.findings.append(decide(finding, mode, threshold))
        results.append(result)
        mem.save(path)
    return results
