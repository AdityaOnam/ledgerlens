"""Read a mailbox: a folder of batches, each a folder of .eml files.

Each email becomes one Document for its body plus one per attachment. Attachments are
decoded to text here (PDF, XLSX and scanned images through ``ingest.convert``); the extractor
never touches MIME or binary formats.
"""

from __future__ import annotations

import email
import email.policy
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from ledgerlens.ingest.convert import OCR, Unsupported, supported, to_text


@dataclass(frozen=True)
class Document:
    doc_id: str
    kind: str  # "email" or "attachment"
    filename: str
    text: str
    sent: date
    sender: str
    recipients: tuple[str, ...]
    subject: str = ""
    source: str = "text"  # how the text was obtained: "text", "pdf", "xlsx" or "ocr"


@dataclass
class Batch:
    name: str
    documents: list[Document] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def as_of(self) -> date | None:
        return max((d.sent for d in self.documents), default=None)


def _body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    return part.get_content() if part is not None else ""


def read_email(
    path: Path, doc_prefix: str, ocr: OCR | None = None
) -> tuple[list[Document], list[str]]:
    """The email body and its attachments as Documents, plus notes on attachments skipped."""
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    sent = parsedate_to_datetime(msg["Date"]).date()
    sender = (getaddresses([msg.get("From", "")]) or [("", "")])[0][1].lower()
    recipients = tuple(
        a.lower() for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))
    )
    subject = str(msg.get("Subject", ""))
    base = f"{doc_prefix}/{path.stem}"
    docs = [Document(base, "email", path.name, _body_text(msg), sent, sender, recipients, subject)]
    skipped: list[str] = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        doc_id = f"{base}/{name}"
        if not supported(name):
            skipped.append(f"{doc_id}: unsupported attachment type")
            continue
        try:
            converted = to_text(name, part.get_content(), ocr)
        except Unsupported as exc:
            skipped.append(f"{doc_id}: {exc}")
            continue
        skipped.extend(f"{doc_id}: {note}" for note in converted.notes)
        docs.append(
            Document(
                doc_id,
                "attachment",
                name,
                converted.text,
                sent,
                sender,
                recipients,
                subject,
                converted.source,
            )
        )
    return docs, skipped


def read_batch(folder: Path, ocr: OCR | None = None) -> Batch:
    batch = Batch(folder.name)
    for path in sorted(folder.glob("*.eml")):
        docs, skipped = read_email(path, folder.name, ocr)
        batch.documents.extend(docs)
        batch.skipped.extend(skipped)
    return batch


def read_mailbox(root: Path, ocr: OCR | None = None) -> list[Batch]:
    """Batches are sub-folders processed in name order; a flat folder is one batch."""
    subdirs = sorted(p for p in root.iterdir() if p.is_dir())
    folders = subdirs if subdirs else [root]
    return [read_batch(f, ocr) for f in folders]
