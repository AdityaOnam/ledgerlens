"""Printed invoices (PDF / OCR text), the completeness check, and both end to end."""

import json
from datetime import date, datetime
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from ledgerlens.app import run
from ledgerlens.cli import choose_ocr
from ledgerlens.decide.policy import Mode
from ledgerlens.domain.models import Action, Evidence, FindingClass, Invoice, InvoiceLine
from ledgerlens.ingest.extract import extract_printed_invoice
from ledgerlens.ingest.mailbox import Document
from ledgerlens.rules.detectors import check_totals
from ledgerlens.store.memory import Memory

PRINTED = """INVOICE INV-CK-410
Vendor: Cloudkeep Ltd.
Issued: 2026-03-01
Due: 2026-03-31
| SKU | Description | Period | Qty | Unit price | Amount |
| CK-STORAGE | Storage (TB-month) | 2026-03-01 to 2026-03-31 | 40 | 23.00 | 920.00 |
| CK-BACKUP | Backup vault | 1 March 2026 - 31 March 2026 | 1 | 1,200.00 | 1,200.00 |
| Credit | SLA-2026-02 | | | | -350.00 |
Total due: $1,770.00
"""


def doc(text, filename="inv.pdf", source="pdf"):
    return Document(
        "b/1/" + filename,
        "attachment",
        filename,
        text,
        date(2026, 3, 1),
        "billing@cloudkeep.example",
        ("ap@acme-robotics.com",),
        source=source,
    )


# --- printed invoice layout -----------------------------------------------------------------


def test_printed_invoice_lines_credits_and_total():
    inv = extract_printed_invoice(doc(PRINTED))
    assert inv.invoice_id == "INV-CK-410" and inv.vendor == "Cloudkeep Ltd."
    assert inv.due == date(2026, 3, 31)
    assert [(x.sku, x.qty, x.unit_price) for x in inv.lines] == [
        ("CK-STORAGE", 40, Decimal("23.00")),
        ("CK-BACKUP", 1, Decimal("1200.00")),
    ]
    assert inv.lines[1].period_start == date(2026, 3, 1)
    assert inv.credits[0].ref == "SLA-2026-02" and inv.credits[0].amount == Decimal("350.00")
    assert inv.total == Decimal("1770.00") == inv.computed_total
    assert inv.evidence.quote == "INVOICE INV-CK-410"
    assert inv.total_evidence.quote == "Total due: $1,770.00"
    for quote in [
        inv.evidence.quote,
        inv.total_evidence.quote,
        *(x.evidence.quote for x in inv.lines),
    ]:
        assert quote in PRINTED


@pytest.mark.parametrize(
    "text",
    [
        "Hello, invoice attached.",
        PRINTED.replace("Total due: $1,770.00\n", ""),
        PRINTED.replace("Due: 2026-03-31\n", ""),
    ],
)
def test_text_that_is_not_a_full_printed_invoice_is_not_one(text):
    assert extract_printed_invoice(doc(text)) is None


# --- completeness ---------------------------------------------------------------------------


def invoice(total, lines=(Decimal("920.00"),)):
    ev = Evidence("d", "q")
    return Invoice(
        "INV-1",
        "V",
        date(2026, 3, 1),
        date(2026, 3, 31),
        tuple(
            InvoiceLine("X-1", "x", date(2026, 3, 1), date(2026, 3, 31), 1, a, a, ev) for a in lines
        ),
        (),
        Decimal(total),
        Evidence("d", "INVOICE INV-1"),
        Evidence("d", f"Total due: {total}"),
    )


def test_invoice_that_adds_up_is_complete():
    assert list(check_totals(Memory(invoices=[invoice("920.00")]))) == []


@pytest.mark.parametrize(("total", "word"), [("1120.00", "more"), ("900.00", "less")])
def test_total_that_does_not_add_up_cannot_be_determined(total, word):
    (f,) = check_totals(Memory(invoices=[invoice(total)]))
    assert f.cls is FindingClass.CANNOT_DETERMINE and f.rule == "printed_total_mismatch"
    assert f.amount == abs(Decimal(total) - Decimal("920.00"))
    assert word in f.summary and f.details["computed_total"] == "920.00"
    assert [e.quote for e in f.evidence] == ["INVOICE INV-1", f"Total due: {total}"]


def test_old_memory_without_total_evidence_still_loads(tmp_path):
    path = tmp_path / "memory.json"
    Memory(invoices=[invoice("920.00")]).save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["invoices"][0]["total_evidence"]  # written before the field existed
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Memory.load(path).invoices[0].total_evidence is None


# --- end to end with PDF and scanned attachments --------------------------------------------

pytest.importorskip("pypdf")
from pdfgen import make_pdf, tiny_jpeg  # noqa: E402

ORDER = """ORDER FORM OF-2026-120
Vendor: Cloudkeep Ltd.
Vendor contact: billing@cloudkeep.example
Term start: 2026-01-01
Term end: 2026-12-31
Auto-renewal: no
Notice period: 0 days
True-up: permitted at contract price

| SKU | Description | Unit price | Quantity |
| CK-STORAGE | Storage (TB-month) | 21.50 | 40 |
| CK-BACKUP | Backup vault | 1,200.00 | 1 |
"""


def eml(path, when, attachments):
    msg = EmailMessage()
    msg["From"] = "billing@cloudkeep.example"
    msg["To"] = "ap@acme-robotics.com"
    msg["Subject"] = "Cloudkeep"
    msg["Date"] = format_datetime(when)
    msg.set_content("Please find attached.")
    for name, data, maintype, subtype in attachments:
        if isinstance(data, str):
            msg.add_attachment(data, subtype=subtype, filename=name)
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    path.write_bytes(msg.as_bytes())


def test_pdf_invoice_and_partly_read_scan_end_to_end(tmp_path):
    box = tmp_path / "box" / "batch_01"
    box.mkdir(parents=True)
    eml(box / "001_order.eml", datetime(2026, 1, 2), [("of.txt", ORDER, "text", "plain")])
    eml(
        box / "002_invoice.eml",
        datetime(2026, 3, 1),
        [("inv.pdf", make_pdf([PRINTED.splitlines()]), "application", "pdf")],
    )
    # The scan of April's invoice: OCR lost the backup line, so the lines fall short of the total.
    scan = PRINTED.replace("INV-CK-410", "INV-CK-455").replace("2026-03", "2026-04")
    scan = scan.replace("March 2026", "April 2026").replace("-04-31", "-04-30")
    scan = scan.replace("23.00 | 920.00", "21.50 | 860.00").replace("1,770.00", "1,710.00")
    misread = "\n".join(x for x in scan.splitlines() if "CK-BACKUP" not in x)
    eml(
        box / "003_scan.eml",
        datetime(2026, 4, 1),
        [("scan.pdf", make_pdf([tiny_jpeg()]), "application", "pdf")],
    )

    results = run(tmp_path / "box", tmp_path / "state", Mode.AUTONOMOUS, ocr=lambda _: misread)
    (r,) = results
    got = {(str(f.cls), f.invoice_id, str(f.amount), f.rule) for f in r.findings}
    assert got == {
        ("price_over_contract", "INV-CK-410", "60.00", "unit_price_above_agreed"),
        ("cannot_determine", "INV-CK-455", "1200.00", "printed_total_mismatch"),
    }
    price = next(f for f in r.findings if f.invoice_id == "INV-CK-410")
    assert price.evidence[0].doc_id == "batch_01/002_invoice/inv.pdf"
    assert price.evidence[0].quote.startswith("| CK-STORAGE | Storage (TB-month) |")
    gap = next(f for f in r.findings if f.invoice_id == "INV-CK-455")
    assert gap.action is Action.REQUEST_DOCUMENT
    assert "batch_01/003_scan/scan.pdf: 1 of 1 page(s) read by OCR" in r.notes


def test_without_ocr_the_scan_is_noted_not_guessed(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    eml(
        box / "003_scan.eml",
        datetime(2026, 4, 1),
        [("s.pdf", make_pdf([tiny_jpeg()]), "application", "pdf")],
    )
    (r,) = run(box, tmp_path / "state")
    assert r.findings == []
    assert r.notes == ["box/003_scan/s.pdf: page 1 is a scan and no OCR engine is available"]


def test_cli_ocr_choice(monkeypatch):
    from ledgerlens.ingest import convert

    assert choose_ocr("off") == (None, "off")
    monkeypatch.setattr(convert.shutil, "which", lambda name: None)
    engine, described = choose_ocr("auto")
    assert engine is None and "unavailable" in described
