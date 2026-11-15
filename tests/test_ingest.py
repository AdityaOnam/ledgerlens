from datetime import date
from decimal import Decimal
from pathlib import Path

from ledgerlens.ingest.extract import (
    Extraction,
    extract,
    extract_agreement,
    extract_email,
    extract_invoice,
)
from ledgerlens.ingest.mailbox import Document, read_mailbox

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"


def doc(text, kind="attachment", sender="billing@brightdesk.io", to=("ap@acme.test",)):
    return Document("t/1", kind, "f", text, date(2026, 1, 1), sender, tuple(to))


ORDER = """ORDER FORM OF-2026-001
Vendor: Brightdesk Inc.
Vendor contact: accounts@brightdesk.io
Term start: 2026-01-01
Term end: 2026-12-31
Auto-renewal: yes
Notice period: 60 days
Renewal uplift cap: 7%
True-up: not permitted

| SKU | Description | Unit price | Quantity |
| BD-PRO | Pro seat | 38.00 | 120 |
"""


def test_order_form_fields_and_evidence():
    agreement, domain = extract_agreement(doc(ORDER))
    assert domain == "brightdesk.io"
    assert agreement.auto_renew and agreement.notice_days == 60
    assert agreement.uplift_cap == Decimal("0.07") and not agreement.true_up_allowed
    term = agreement.term_for("BD-PRO")
    assert term.unit_price == Decimal("38.00") and term.licensed_qty == 120
    assert term.evidence.quote == "| BD-PRO | Pro seat | 38.00 | 120 |"


def test_invoice_lines_and_credits():
    text = (
        "invoice_id,INV-1\nvendor,V\nissued,2026-02-01\ndue,2026-03-01\ntotal,10.00\n"
        "line,sku,description,period_start,period_end,qty,unit_price,amount\n"
        "line,X-1,thing,2026-02-01,2026-02-28,2,10.00,20.00\ncredit,SLA-1,-10.00\n"
    )
    inv = extract_invoice(doc(text))
    assert inv.lines[0].qty == 2 and inv.lines[0].amount == Decimal("20.00")
    assert inv.credits[0].ref == "SLA-1" and inv.credits[0].amount == Decimal("10.00")


def test_email_needs_a_known_vendor():
    body = "Please cancel BD-ANALYTICS effective 2026-02-01."
    assert extract_email(doc(body, "email", sender="a@unknown.test"), {}).cancellations == []
    found = extract_email(doc(body, "email"), {"brightdesk.io": "Brightdesk Inc."})
    assert found.cancellations[0].sku == "BD-ANALYTICS"
    assert found.cancellations[0].evidence.quote == body.rstrip(".")


def test_credit_promise_quote():
    body = "We will apply a service credit of $350.00 to your next invoice (ref SLA-2026-02)."
    found = extract_email(doc(body, "email"), {"brightdesk.io": "B"})
    assert found.credits[0].amount == Decimal("350.00") and found.credits[0].ref == "SLA-2026-02"


def test_unrecognised_attachment_is_reported_not_dropped():
    assert extract([doc("hello")], {}).unread == ["t/1: layout not recognised"]


def test_sample_mailbox_reads_cleanly():
    batches = read_mailbox(SAMPLES)
    assert [b.name for b in batches] == ["batch_01", "batch_02"]
    for b in batches:
        assert extract(b.documents, {}).unread == []


def test_fallback_reads_what_the_layout_cannot():
    seen = []

    def fallback(d, domains):
        seen.append(d.doc_id)
        return Extraction(vendor_domains={"quill.test": "Quillstack"})

    x = extract([doc("free-form prose", sender="ar@quill.test")], {}, fallback=fallback)
    assert seen == ["t/1"] and x.unread == [] and x.vendor_domains == {"quill.test": "Quillstack"}


def test_fallback_returning_none_keeps_the_unread_note():
    x = extract([doc("hello")], {}, fallback=lambda d, domains: None)
    assert x.unread == ["t/1: layout not recognised"]


def test_fallback_only_sees_known_vendor_emails_without_stock_sentences():
    seen = []

    def fallback(d, domains):
        seen.append(d.text)
        return None

    known = {"brightdesk.io": "Brightdesk Inc."}
    stock = doc("Please cancel BD-ANALYTICS effective 2026-02-01.", "email")
    prose = doc("Let's drop analytics from next month.", "email")
    stranger = doc("Hello there.", "email", sender="x@unknown.test")
    x = extract([stock, prose, stranger], known, fallback=fallback)
    assert seen == ["Let's drop analytics from next month."]
    assert len(x.cancellations) == 1


def test_signatory_is_read_from_the_signed_line():
    signed = ORDER.replace(
        "True-up: not permitted", "True-up: not permitted\nSigned: Priya Raman, VP Finance"
    )
    agreement, _ = extract_agreement(doc(signed))
    assert agreement.signed_by == "Priya Raman, VP Finance"
    assert extract_agreement(doc(ORDER))[0].signed_by == ""


def test_price_agreed_by_email_names_the_customer_party():
    body = (
        "Hi Priya,\n\nFollowing our call, the price for BD-PRO will be $34.00 per seat "
        "effective 2026-08-01. Everything else stays the same.\n"
    )
    x = extract_email(
        doc(body, kind="email", to=("priya@acme.test",)), {"brightdesk.io": "Brightdesk Inc."}
    )
    (p,) = x.prices
    assert (p.vendor, p.sku, str(p.unit_price), p.effective) == (
        "Brightdesk Inc.",
        "BD-PRO",
        "34.00",
        date(2026, 8, 1),
    )
    assert p.agreed_by == "priya@acme.test"
    assert p.evidence.quote.endswith("effective 2026-08-01")
    assert not x.empty


def test_customer_written_price_email_is_agreed_by_the_sender():
    body = "Confirming the new rate for BD-PRO of $34.00 per seat, effective 2026-08-01.\n"
    x = extract_email(
        doc(body, kind="email", sender="dev@acme.test", to=("billing@brightdesk.io",)),
        {"brightdesk.io": "Brightdesk Inc."},
    )
    assert [p.agreed_by for p in x.prices] == ["dev@acme.test"]


def test_cancellation_and_credit_sentences_are_not_prices():
    body = (
        "Please cancel BD-ANALYTICS effective 2026-02-01.\n"
        "We will apply a service credit of $350.00 to your next invoice (ref SLA-2026-02).\n"
    )
    x = extract_email(doc(body, kind="email"), {"brightdesk.io": "Brightdesk Inc."})
    assert x.prices == [] and len(x.cancellations) == 1 and len(x.credits) == 1
