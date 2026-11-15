"""Turn documents into typed facts.

This is the layout-based extractor: it understands the plain-text order forms, CSV invoices,
printed invoices (the text of a PDF or a scan) and the stock sentences vendors use in email.
Every fact keeps the exact line it was read from.

Documents the layout cannot read can be handed to a fallback reader (the model-based extractor
in ``ingest.llm``). Both produce the same Extraction, so rules never know which one read a fact.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ledgerlens.domain.dates import parse_date
from ledgerlens.domain.models import (
    Agreement,
    AppliedCredit,
    Cancellation,
    CreditPromise,
    DocumentReference,
    Evidence,
    Invoice,
    InvoiceLine,
    PriceStatement,
    PriceTerm,
)
from ledgerlens.domain.money import money, percent
from ledgerlens.ingest.mailbox import Document

SKU = r"[A-Z]{2,}-[A-Z0-9]+(?:-[A-Z0-9]+)*"
DATE = r"\d{4}-\d{2}-\d{2}|\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2}, \d{4}"
DOC_REF = r"(?:OF|AM)-\d{4}-\d+"


FACT_LISTS = ("agreements", "invoices", "cancellations", "credits", "references", "prices")


@dataclass
class Extraction:
    agreements: list[Agreement] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    cancellations: list[Cancellation] = field(default_factory=list)
    credits: list[CreditPromise] = field(default_factory=list)
    references: list[DocumentReference] = field(default_factory=list)
    prices: list[PriceStatement] = field(default_factory=list)
    vendor_domains: dict[str, str] = field(default_factory=dict)
    unread: list[str] = field(default_factory=list)

    def extend(self, other: Extraction) -> None:
        for name in FACT_LISTS + ("unread",):
            getattr(self, name).extend(getattr(other, name))
        self.vendor_domains.update(other.vendor_domains)

    @property
    def empty(self) -> bool:
        return not any(getattr(self, name) for name in FACT_LISTS)


# Reads one document the layout did not understand; None means "not read either".
Fallback = Callable[[Document, dict[str, str]], Extraction | None]
# Anything that turns a batch of documents into facts: the layout `extract`, or an LLM extractor.
Extractor = Callable[[list[Document], dict[str, str]], Extraction]


# --- order forms and amendments -------------------------------------------------------------

_HEADER = re.compile(rf"^(ORDER FORM|AMENDMENT)\s+({DOC_REF})(?:\s+to\s+({DOC_REF}))?", re.M)


def _fields(text: str) -> dict[str, tuple[str, str]]:
    """'Key: value' lines -> {lower key: (value, original line)}."""
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z][A-Za-z \-]+?):\s*(.+?)\s*$", line)
        if m:
            out.setdefault(m.group(1).lower(), (m.group(2), line.strip()))
    return out


def _price_table(text: str, doc_id: str) -> list[PriceTerm]:
    terms = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(SKU, cells[0]):
            sku, desc, price, qty = cells
            terms.append(
                PriceTerm(
                    sku,
                    desc,
                    money(price),
                    int(qty.replace(",", "")),
                    Evidence(doc_id, line.strip()),
                )
            )
    return terms


def extract_agreement(doc: Document) -> tuple[Agreement, str] | None:
    """Return the agreement and the vendor's email domain (from 'Vendor contact')."""
    head = _HEADER.search(doc.text)
    if not head:
        return None
    f = _fields(doc.text)

    def val(key: str, default: str | None = None) -> str | None:
        return f[key][0] if key in f else default

    contact = val("vendor contact", "") or ""
    domain = contact.split("@")[-1].lower() if "@" in contact else ""
    cap = val("renewal uplift cap")
    effective = val("effective")
    return Agreement(
        agreement_id=head.group(2),
        vendor=val("vendor", "") or "",
        start=parse_date(val("term start") or effective or ""),
        end=parse_date(val("term end") or ""),
        auto_renew=(val("auto-renewal", "no") or "").lower().startswith("y"),
        notice_days=int(re.sub(r"\D", "", val("notice period", "0") or "0") or 0),
        uplift_cap=percent(cap) if cap else None,
        true_up_allowed=(val("true-up", "") or "").lower().startswith("permitted"),
        prices=tuple(_price_table(doc.text, doc.doc_id)),
        evidence=Evidence(doc.doc_id, head.group(0)),
        amends=head.group(3),
        effective=parse_date(effective) if effective else None,
        signed_by=val("signed", "") or "",
    ), domain


# --- invoices -------------------------------------------------------------------------------


def extract_invoice(doc: Document) -> Invoice | None:
    rows = list(csv.reader(io.StringIO(doc.text)))
    head = {r[0].strip().lower(): r[1].strip() for r in rows if len(r) == 2}
    if "invoice_id" not in head:
        return None
    lines, credits = [], []
    for r in rows:
        if not r:
            continue
        raw = ",".join(r)
        if r[0] == "line" and len(r) == 8 and r[1] != "sku":
            _, sku, desc, ps, pe, qty, unit, amount = (c.strip() for c in r)
            lines.append(
                InvoiceLine(
                    sku,
                    desc,
                    parse_date(ps),
                    parse_date(pe),
                    int(qty),
                    money(unit),
                    money(amount),
                    Evidence(doc.doc_id, raw),
                )
            )
        elif r[0] == "credit" and len(r) == 3:
            credits.append(AppliedCredit(r[1].strip(), -money(r[2]), Evidence(doc.doc_id, raw)))
    total_row = next((r for r in rows if len(r) == 2 and r[0].strip().lower() == "total"), None)
    return Invoice(
        invoice_id=head["invoice_id"],
        vendor=head.get("vendor", ""),
        issued=parse_date(head["issued"]),
        due=parse_date(head["due"]),
        lines=tuple(lines),
        credits=tuple(credits),
        total=money(head.get("total", "0")),
        evidence=Evidence(doc.doc_id, f"invoice_id,{head['invoice_id']}"),
        total_evidence=Evidence(doc.doc_id, ",".join(total_row)) if total_row else None,
    )


# A printed invoice, as text comes out of a PDF or OCR:
#
#   INVOICE INV-CK-410
#   Vendor: Cloudkeep Ltd.
#   Issued: 2026-03-01
#   Due: 2026-03-31
#   | SKU | Description | Period | Qty | Unit price | Amount |
#   | CK-STORAGE | Storage (TB-month) | 2026-03-01 to 2026-03-31 | 40 | 21.50 | 860.00 |
#   | Credit | SLA-2026-02 | | | | -350.00 |
#   Total due: 510.00

_INVOICE_HEADER = re.compile(r"^\s*INVOICE\s+(?:NO\.?\s*|#\s*)?([A-Z]{2,}-[A-Z0-9-]+)\b", re.M)
_PERIOD = re.compile(rf"^({DATE})\s+(?:to|-|–|—)\s+({DATE})$")
_TOTAL = re.compile(r"^\s*(?:invoice\s+)?total(?:\s+due)?\s*:\s*(.+?)\s*$", re.I | re.M)


def extract_printed_invoice(doc: Document) -> Invoice | None:
    head = _INVOICE_HEADER.search(doc.text)
    total = _TOTAL.search(doc.text)
    if not head or not total:
        return None
    f = _fields(doc.text)
    if "issued" not in f or "due" not in f:
        return None
    lines, credits = [], []
    for raw in doc.text.splitlines():
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if len(cells) != 6:
            continue
        quote = raw.strip()
        if cells[0].lower() == "credit" and cells[1]:
            credits.append(AppliedCredit(cells[1], -money(cells[5]), Evidence(doc.doc_id, quote)))
            continue
        period = _PERIOD.match(cells[2])
        if not re.fullmatch(SKU, cells[0]) or not period:
            continue
        lines.append(
            InvoiceLine(
                cells[0],
                cells[1],
                parse_date(period.group(1)),
                parse_date(period.group(2)),
                int(cells[3].replace(",", "")),
                money(cells[4]),
                money(cells[5]),
                Evidence(doc.doc_id, quote),
            )
        )
    return Invoice(
        invoice_id=head.group(1),
        vendor=f["vendor"][0] if "vendor" in f else "",
        issued=parse_date(f["issued"][0]),
        due=parse_date(f["due"][0]),
        lines=tuple(lines),
        credits=tuple(credits),
        total=money(total.group(1)),
        evidence=Evidence(doc.doc_id, head.group(0).strip()),
        total_evidence=Evidence(doc.doc_id, total.group(0).strip()),
    )


# --- email statements -----------------------------------------------------------------------

_CANCEL = re.compile(
    rf"[^.\n]*\bcancel\w*\b[^.\n]*?\b({SKU})\b[^.\n]*?\beffective\s+({DATE})[^.\n]*", re.I
)
_CREDIT = re.compile(
    r"[^.\n]*\bcredit of\s+\$?([\d,]+\.\d{2})[^.\n]*?\(ref\s+([A-Z0-9-]+)\)[^.\n]*", re.I
)
# "the price for BD-PRO will be $34.00 per seat effective 2026-08-01"
_PRICE = re.compile(
    rf"[^.\n]*\b(?:price|rate)\b[^.\n]*?\b({SKU})\b[^.\n]*?\$([\d,]+\.\d{{2}})"
    rf"[^.\n]*?\beffective\s+({DATE})[^.\n]*",
    re.I,
)
_REF = re.compile(rf"[^.\n]*\b(order form|amendment)\s+({DOC_REF})\b[^.\n]*", re.I)


def _domain(addr: str) -> str:
    return addr.split("@")[-1].lower()


def email_vendor(doc: Document, vendor_domains: dict[str, str]) -> str | None:
    """The vendor an email is with, judged only by sender and recipient domains."""
    return next(
        (
            vendor_domains[_domain(a)]
            for a in (doc.sender, *doc.recipients)
            if _domain(a) in vendor_domains
        ),
        None,
    )


def customer_party(doc: Document, vendor_domains: dict[str, str]) -> str:
    """The customer-side address on an email: the sender, unless the sender is the vendor."""
    if _domain(doc.sender) not in vendor_domains:
        return doc.sender
    return next((a for a in doc.recipients if _domain(a) not in vendor_domains), doc.sender)


def extract_email(doc: Document, vendor_domains: dict[str, str]) -> Extraction:
    out = Extraction()
    parties = [doc.sender, *doc.recipients]
    vendor = email_vendor(doc, vendor_domains)
    if vendor is None:
        return out
    for m in _CANCEL.finditer(doc.text):
        out.cancellations.append(
            Cancellation(
                vendor,
                m.group(1),
                parse_date(m.group(2)),
                doc.sender,
                Evidence(doc.doc_id, m.group(0).strip()),
            )
        )
    for m in _CREDIT.finditer(doc.text):
        out.credits.append(
            CreditPromise(
                vendor,
                m.group(2),
                money(m.group(1)),
                doc.sent,
                Evidence(doc.doc_id, m.group(0).strip()),
            )
        )
    for m in _PRICE.finditer(doc.text):
        out.prices.append(
            PriceStatement(
                vendor,
                m.group(1),
                money(m.group(2)),
                parse_date(m.group(3)),
                customer_party(doc, vendor_domains),
                Evidence(doc.doc_id, m.group(0).strip()),
            )
        )
    holder = next((a for a in parties if _domain(a) in vendor_domains), doc.sender)
    for m in _REF.finditer(doc.text):
        out.references.append(
            DocumentReference(
                vendor,
                m.group(2),
                m.group(1).lower(),
                holder,
                Evidence(doc.doc_id, m.group(0).strip()),
            )
        )
    return out


def extract(
    documents: list[Document],
    vendor_domains: dict[str, str],
    fallback: Fallback | None = None,
) -> Extraction:
    """Attachments first: agreements and invoices teach us which domain is which vendor.
    Emails are read afterwards, so a cover note can be tied to its vendor.

    With a ``fallback``, an attachment whose layout is not recognised, or an email from a known
    vendor in which no stock sentence matched, is passed to it instead of being given up on."""
    out = Extraction()

    def learn(domain: str, vendor: str) -> None:
        if domain and vendor and domain not in vendor_domains:
            out.vendor_domains.setdefault(domain, vendor)

    def known() -> dict[str, str]:
        return {**out.vendor_domains, **vendor_domains}

    emails = []
    for doc in documents:
        if doc.kind == "email":
            emails.append(doc)
            continue
        found = extract_agreement(doc)
        if found:
            agreement, domain = found
            out.agreements.append(agreement)
            learn(domain, agreement.vendor)
            continue
        invoice = extract_invoice(doc) or extract_printed_invoice(doc)
        if invoice:
            out.invoices.append(invoice)
            learn(_domain(doc.sender), invoice.vendor)
            continue
        read = fallback(doc, known()) if fallback else None
        if read is None:
            out.unread.append(f"{doc.doc_id}: layout not recognised")
            continue
        out.extend(read)
        for domain, vendor in read.vendor_domains.items():
            learn(domain, vendor)
    domains = known()
    for doc in emails:
        found_email = extract_email(doc, domains)
        if found_email.empty and fallback and email_vendor(doc, domains):
            found_email = fallback(doc, domains) or found_email
        out.extend(found_email)
    return out
