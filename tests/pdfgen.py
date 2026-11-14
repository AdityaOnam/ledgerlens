"""A minimal PDF writer for tests: text pages (one line per text row) and image-only pages.

Written by hand so the tests need no PDF-writing library; pypdf reads what this writes.
"""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_stream(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 10 Tf", "12 TL", "40 800 Td"]
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def make_pdf(pages: list[list[str] | bytes]) -> bytes:
    """Each page is a list of text lines, or JPEG bytes for a scanned (image-only) page."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def stream(data: bytes, extra: str = "") -> bytes:
        head = f"<< /Length {len(data)}{extra} >>\nstream\n".encode()
        return head + data + b"\nendstream"

    catalog = add(b"")  # filled in at the end
    pages_obj = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for page in pages:
        if isinstance(page, bytes):
            img = add(
                stream(
                    page,
                    " /Type /XObject /Subtype /Image /Width 8 /Height 8"
                    " /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode",
                )
            )
            content = add(stream(b"q 200 0 0 200 100 500 cm /Im1 Do Q"))
            resources = f"<< /XObject << /Im1 {img} 0 R >> >>"
        else:
            content = add(stream(_text_stream(page)))
            resources = f"<< /Font << /F1 {font} 0 R >> >>"
        kids.append(
            add(
                f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 595 842] "
                f"/Resources {resources} /Contents {content} 0 R >>".encode()
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    kid_refs = " ".join(f"{k} 0 R" for k in kids)
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{kid_refs}] /Count {len(kids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (8, 8), 255).save(buf, "JPEG")
    return buf.getvalue()
