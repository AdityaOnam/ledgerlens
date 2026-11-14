"""Turn binary attachments (PDF, XLSX, scanned images) into plain text.

Everything downstream (the layout reader, the model, the grounding check) works on text, so
each format is converted once, here, and the result becomes the document's text. Quotes are
then checked against exactly what was converted.

* PDF: the text layer of each page, via ``pypdf``. A page with no text layer is treated as a
  scan: the images on it are passed to OCR.
* XLSX: every sheet, row by row, written as CSV, via ``openpyxl``. A spreadsheet laid out like
  the CSV invoices is then read by the same code.
* PNG / JPEG / TIFF: OCR.

All three libraries are optional extras (``ledgerlens[pdf]``, ``[xlsx]``, ``[ocr]``). When one
is missing the attachment is skipped with a note that says what to install, never dropped
silently. OCR is an injectable callable so tests, and other engines, can stand in for
Tesseract.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

TEXT_TYPES = {".txt", ".csv", ".md"}
PDF_TYPES = {".pdf"}
SHEET_TYPES = {".xlsx", ".xlsm"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}

# Reads the text in one image (encoded PNG / JPEG / TIFF bytes).
OCR = Callable[[bytes], str]


class Unsupported(Exception):
    """This attachment cannot be turned into text here; the message says why."""


@dataclass
class Converted:
    text: str
    source: str  # "text", "pdf", "xlsx" or "ocr"
    notes: list[str] = field(default_factory=list)


def supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in TEXT_TYPES | PDF_TYPES | SHEET_TYPES | IMAGE_TYPES


def _require(module: str, extra: str) -> None:
    if importlib.util.find_spec(module) is None:
        raise Unsupported(f'needs {module}: pip install "ledgerlens[{extra}]"')


# --- PDF ------------------------------------------------------------------------------------


def pdf_to_text(data: bytes, ocr: OCR | None = None) -> Converted:
    _require("pypdf", "pdf")
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = list(reader.pages)
    except Exception as exc:  # pypdf raises many types for damaged files
        raise Unsupported(f"unreadable PDF: {exc}") from exc
    texts: list[str] = []
    notes: list[str] = []
    scanned = 0
    for number, page in enumerate(pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            texts.append(text)
            continue
        images = _page_images(page)
        if not images:
            continue
        if ocr is None:
            notes.append(f"page {number} is a scan and no OCR engine is available")
            continue
        scanned += 1
        texts.extend(t for t in (ocr(img).strip() for img in images) if t)
    if not texts:
        raise Unsupported("; ".join(notes) or "PDF has no text")
    if scanned:
        notes.append(f"{scanned} of {len(pages)} page(s) read by OCR")
    return Converted("\n".join(texts) + "\n", "ocr" if scanned else "pdf", notes)


def _page_images(page: Any) -> list[bytes]:
    try:
        return [img.data for img in page.images]
    except Exception:  # an image pypdf cannot decode is the same as no image
        return []


# --- XLSX -----------------------------------------------------------------------------------


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value).strip()


def xlsx_to_text(data: bytes) -> Converted:
    """Every sheet as CSV, sheets separated by a blank line. Trailing empty cells are dropped,
    so a two-cell 'invoice_id,INV-1' row stays two cells however wide the sheet is."""
    _require("openpyxl", "xlsx")
    import openpyxl

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise Unsupported(f"unreadable spreadsheet: {exc}") from exc
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    try:
        for i, sheet in enumerate(book.worksheets):
            if i:
                out.write("\n")
            for row in sheet.iter_rows(values_only=True):
                cells = [_cell(v) for v in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    writer.writerow(cells)
    finally:
        book.close()
    text = out.getvalue()
    if not text.strip():
        raise Unsupported("spreadsheet is empty")
    return Converted(text, "xlsx")


# --- images ---------------------------------------------------------------------------------


def image_to_text(data: bytes, ocr: OCR | None) -> Converted:
    if ocr is None:
        raise Unsupported("image needs OCR and no OCR engine is available")
    text = ocr(data).strip()
    if not text:
        raise Unsupported("OCR found no text")
    return Converted(text + "\n", "ocr")


class TesseractOCR:
    """OCR through the Tesseract binary (``pytesseract`` + Pillow)."""

    def __call__(self, image: bytes) -> str:
        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            return pytesseract.image_to_string(img)


def default_ocr() -> OCR | None:
    """Tesseract if both the Python packages and the binary are present, otherwise None."""
    have = all(importlib.util.find_spec(m) for m in ("pytesseract", "PIL"))
    return TesseractOCR() if have and shutil.which("tesseract") else None


# --- dispatch -------------------------------------------------------------------------------


def to_text(filename: str, payload: bytes | str, ocr: OCR | None = None) -> Converted:
    """Convert one attachment by its file extension. Raises Unsupported with a reason."""
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_TYPES:
        text = payload if isinstance(payload, str) else payload.decode("utf-8", errors="replace")
        return Converted(text, "text")
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    if suffix in PDF_TYPES:
        return pdf_to_text(data, ocr)
    if suffix in SHEET_TYPES:
        return xlsx_to_text(data)
    if suffix in IMAGE_TYPES:
        return image_to_text(data, ocr)
    raise Unsupported("unsupported attachment type")
