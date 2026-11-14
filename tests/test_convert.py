"""PDF, XLSX and OCR conversion, and attachments of those types arriving by email."""

import io
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from ledgerlens.ingest import convert
from ledgerlens.ingest.convert import Unsupported, to_text
from ledgerlens.ingest.extract import extract
from ledgerlens.ingest.mailbox import read_email

pytest.importorskip("pypdf")
openpyxl = pytest.importorskip("openpyxl")

from pdfgen import make_pdf, tiny_jpeg  # noqa: E402

PRINTED = [
    "INVOICE INV-CK-410",
    "Vendor: Cloudkeep Ltd.",
    "Issued: 2026-03-01",
    "Due: 2026-03-31",
    "| SKU | Description | Period | Qty | Unit price | Amount |",
    "| CK-STORAGE | Storage (TB-month) | 2026-03-01 to 2026-03-31 | 40 | 21.50 | 860.00 |",
    "| Credit | SLA-2026-02 | | | | -350.00 |",
    "Total due: 510.00",
]


def fake_ocr(text):
    seen = []

    def ocr(image: bytes) -> str:
        seen.append(image)
        return text

    ocr.seen = seen
    return ocr


def xlsx(rows, extra_sheet=None) -> bytes:
    book = openpyxl.Workbook()
    for row in rows:
        book.active.append(row)
    if extra_sheet:
        sheet = book.create_sheet("notes")
        for row in extra_sheet:
            sheet.append(row)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


# --- PDF ------------------------------------------------------------------------------------


def test_pdf_text_layer_keeps_one_line_per_row():
    got = to_text("inv.pdf", make_pdf([PRINTED]))
    assert got.source == "pdf" and got.notes == []
    assert got.text.splitlines() == PRINTED


def test_pdf_pages_are_joined_in_order():
    got = to_text("inv.pdf", make_pdf([PRINTED[:4], PRINTED[4:]]))
    assert got.text.splitlines() == PRINTED


def test_scanned_pdf_page_goes_to_ocr():
    ocr = fake_ocr("\n".join(PRINTED))
    got = to_text("scan.pdf", make_pdf([tiny_jpeg()]), ocr)
    assert got.source == "ocr" and len(ocr.seen) == 1
    assert got.text.splitlines() == PRINTED
    assert got.notes == ["1 of 1 page(s) read by OCR"]


def test_mixed_pdf_only_ocrs_the_page_without_text():
    ocr = fake_ocr("\n".join(PRINTED[4:]))
    got = to_text("mixed.pdf", make_pdf([PRINTED[:4], tiny_jpeg()]), ocr)
    assert got.text.splitlines() == PRINTED and len(ocr.seen) == 1
    assert got.notes == ["1 of 2 page(s) read by OCR"]


def test_scanned_pdf_without_ocr_is_skipped_with_a_reason():
    with pytest.raises(Unsupported, match="page 1 is a scan and no OCR engine"):
        to_text("scan.pdf", make_pdf([tiny_jpeg()]))


def test_partly_scanned_pdf_without_ocr_keeps_the_text_and_notes_the_gap():
    got = to_text("mixed.pdf", make_pdf([PRINTED, tiny_jpeg()]))
    assert got.text.splitlines() == PRINTED
    assert got.notes == ["page 2 is a scan and no OCR engine is available"]


def test_damaged_pdf_is_unsupported_not_a_crash():
    with pytest.raises(Unsupported, match="unreadable PDF"):
        to_text("broken.pdf", b"%PDF-1.4 this is not a pdf")


# --- XLSX -----------------------------------------------------------------------------------

INVOICE_ROWS = [
    ["invoice_id", "INV-PW-120"],
    ["vendor", "Pagewise"],
    ["issued", datetime(2026, 4, 1)],
    ["due", datetime(2026, 5, 1)],
    ["total", 264.0],
    ["line", "sku", "description", "period_start", "period_end", "qty", "unit_price", "amount"],
    ["line", "PW-TEAM", "Team plan", datetime(2026, 4, 1), datetime(2026, 4, 30), 20, 13.2, 264],
]


def test_xlsx_becomes_csv_the_invoice_reader_understands():
    got = to_text("inv.xlsx", xlsx(INVOICE_ROWS))
    assert got.source == "xlsx"
    assert "line,PW-TEAM,Team plan,2026-04-01,2026-04-30,20,13.2,264" in got.text
    assert "invoice_id,INV-PW-120\n" in got.text  # no trailing empty cells
    inv = extract([_doc(got.text)], {}).invoices[0]
    assert inv.issued == date(2026, 4, 1) and str(inv.lines[0].unit_price) == "13.20"
    assert inv.total == inv.computed_total


def test_xlsx_cells_with_commas_are_quoted_and_sheets_separated():
    got = to_text("x.xlsx", xlsx([["a, b", 1.5]], extra_sheet=[["second"]]))
    assert got.text == '"a, b",1.5\n\nsecond\n'


def test_empty_or_damaged_xlsx_is_unsupported():
    with pytest.raises(Unsupported, match="empty"):
        to_text("e.xlsx", xlsx([]))
    with pytest.raises(Unsupported, match="unreadable spreadsheet"):
        to_text("e.xlsx", b"PK not really a zip")


# --- images and dispatch --------------------------------------------------------------------


def test_image_attachment_is_read_by_ocr():
    got = to_text("scan.PNG", b"\x89PNG...", fake_ocr("INVOICE INV-1\n"))
    assert got.source == "ocr" and got.text == "INVOICE INV-1\n"


def test_image_without_ocr_or_text_is_unsupported():
    with pytest.raises(Unsupported, match="no OCR engine"):
        to_text("scan.jpg", b"...")
    with pytest.raises(Unsupported, match="no text"):
        to_text("scan.jpg", b"...", fake_ocr("   "))


def test_unknown_types_are_unsupported():
    assert not convert.supported("deck.pptx")
    with pytest.raises(Unsupported, match="unsupported attachment type"):
        to_text("deck.pptx", b"")


def test_missing_library_names_the_extra(monkeypatch):
    monkeypatch.setattr(convert.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(Unsupported, match=r'pip install "ledgerlens\[pdf\]"'):
        to_text("a.pdf", b"%PDF")
    with pytest.raises(Unsupported, match=r'pip install "ledgerlens\[xlsx\]"'):
        to_text("a.xlsx", b"PK")


def test_default_ocr_needs_the_tesseract_binary(monkeypatch):
    monkeypatch.setattr(convert.shutil, "which", lambda name: None)
    assert convert.default_ocr() is None


# --- arriving by email ----------------------------------------------------------------------


def _doc(text):
    from ledgerlens.ingest.mailbox import Document

    return Document("t/1", "attachment", "f", text, date(2026, 4, 1), "ar@pagewise.app", ())


def write_eml(path, attachments):
    msg = EmailMessage()
    msg["From"] = "billing@cloudkeep.example"
    msg["To"] = "ap@acme-robotics.com"
    msg["Subject"] = "Your invoice"
    msg["Date"] = format_datetime(datetime(2026, 3, 1, 9, 0))
    msg.set_content("Invoice attached.")
    for name, data, (main, sub) in attachments:
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    path.write_bytes(msg.as_bytes())
    return path


def test_email_attachments_are_converted_and_tagged(tmp_path):
    eml = write_eml(
        tmp_path / "m.eml",
        [
            ("inv.pdf", make_pdf([PRINTED]), ("application", "pdf")),
            ("inv.xlsx", xlsx(INVOICE_ROWS), ("application", "vnd.ms-excel")),
            ("scan.png", b"\x89PNG", ("image", "png")),
            ("deck.pptx", b"", ("application", "octet-stream")),
        ],
    )
    docs, skipped = read_email(eml, "b1", ocr=fake_ocr("\n".join(PRINTED)))
    assert [(d.filename, d.source) for d in docs] == [
        ("m.eml", "text"),
        ("inv.pdf", "pdf"),
        ("inv.xlsx", "xlsx"),
        ("scan.png", "ocr"),
    ]
    assert skipped == ["b1/m/deck.pptx: unsupported attachment type"]


def test_scans_without_ocr_are_skipped_with_a_note(tmp_path):
    eml = write_eml(
        tmp_path / "m.eml", [("scan.pdf", make_pdf([tiny_jpeg()]), ("application", "pdf"))]
    )
    docs, skipped = read_email(eml, "b1")
    assert [d.filename for d in docs] == ["m.eml"]
    assert skipped == ["b1/m/scan.pdf: page 1 is a scan and no OCR engine is available"]
