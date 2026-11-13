from datetime import date
from decimal import Decimal

from ledgerlens.ingest.grounding import SCHEMA, facts_from_model, grounded, mentions_amount
from ledgerlens.ingest.mailbox import Document

LETTER = """Hi Acme team,

Thanks for signing with Quillstack. To confirm what we agreed on the call: your subscription
(reference OF-2026-310) runs from 1 March 2026 to 28 February 2027 and renews automatically
unless either side gives 30 days' notice. Editor seats are $21.50 each and you have 40 of them.
Renewal increases are capped at 5%.

Best,
Rhea Calloway, Quillstack
"""

INVOICE = """Quillstack invoice QS-5521, issued 1 April 2026, due 1 May 2026.
Editor seats QS-EDITOR for April 2026: 40 x $21.50 = $860.00.
Amount due: $860.00
"""


def doc(text, kind="attachment", sender="rhea@quillstack.test", doc_id="b/1"):
    return Document(doc_id, kind, "f", text, date(2026, 3, 2), sender, ("ap@acme.test",))


def agreement(**over):
    a = {
        "agreement_id": "OF-2026-310",
        "vendor": "Quillstack",
        "vendor_contact_email": "rhea@quillstack.test",
        "start": "2026-03-01",
        "end": "2027-02-28",
        "auto_renew": True,
        "notice_days": 30,
        "uplift_cap_percent": "5",
        "true_up_allowed": False,
        "amends": "",
        "effective": "",
        "quote": "your subscription\n(reference OF-2026-310)",
        "prices": [
            {
                "sku": "QS-EDITOR",
                "description": "Editor seat",
                "unit_price": "21.50",
                "licensed_qty": 40,
                "quote": "Editor seats are $21.50 each and you have 40 of them.",
            }
        ],
    }
    a.update(over)
    return {"agreements": [a]}


def test_quotes_must_be_verbatim():
    assert grounded("Renewal increases are capped at 5%.", LETTER)
    assert not grounded("Renewal increases are capped at 7%.", LETTER)
    assert not grounded("5%", LETTER)  # too short to prove anything
    assert grounded("To confirm what we agreed", LETTER.replace("\n", "\r\n"))


def test_amount_must_be_in_the_quote():
    assert mentions_amount("40 x $21.50 = $860.00.", Decimal("860.00"))
    assert mentions_amount("credit -1,250.00", Decimal("-1250.00"))
    assert not mentions_amount("40 x $21.50", Decimal("860.00"))


def test_grounded_agreement_becomes_a_fact():
    x = facts_from_model(doc(LETTER), agreement(), {})
    assert x.unread == []
    a = x.agreements[0]
    assert a.agreement_id == "OF-2026-310" and a.notice_days == 30
    assert a.uplift_cap == Decimal("0.05") and a.amends is None
    assert a.term_for("QS-EDITOR").unit_price == Decimal("21.50")
    assert a.evidence.doc_id == "b/1"
    assert x.vendor_domains == {"quillstack.test": "Quillstack"}


def test_invented_quote_rejects_the_agreement():
    x = facts_from_model(doc(LETTER), agreement(quote="Agreement OF-2026-310 signed by both"), {})
    assert x.agreements == []
    assert x.unread[0].startswith("b/1: dropped agreement OF-2026-310: quote not found")


def test_price_that_its_quote_does_not_support_is_dropped():
    data = agreement()
    data["agreements"][0]["prices"][0]["unit_price"] = "19.00"
    x = facts_from_model(doc(LETTER), data, {})
    assert x.agreements[0].prices == ()
    assert "amount 19.00 not in its quote" in x.unread[0]


def test_invoice_with_an_ungrounded_line_is_dropped_whole():
    good_line = {
        "sku": "QS-EDITOR",
        "description": "Editor seats",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "qty": 40,
        "unit_price": "21.50",
        "amount": "860.00",
        "quote": "Editor seats QS-EDITOR for April 2026: 40 x $21.50 = $860.00.",
    }
    inv = {
        "invoice_id": "QS-5521",
        "vendor": "Quillstack",
        "issued": "2026-04-01",
        "due": "2026-05-01",
        "total": "860.00",
        "quote": "Quillstack invoice QS-5521",
        "lines": [good_line],
        "credits": [],
    }
    x = facts_from_model(doc(INVOICE), {"invoices": [inv]}, {})
    assert x.invoices[0].lines[0].amount == Decimal("860.00") and x.unread == []

    bad = {**good_line, "sku": "QS-ADMIN", "quote": "Admin seats QS-ADMIN: 2 x $30.00 = $60.00"}
    x = facts_from_model(doc(INVOICE), {"invoices": [{**inv, "lines": [good_line, bad]}]}, {})
    assert x.invoices == [] and "QS-5521" in x.unread[0]


EMAIL = """Hi Rhea, please stop the QS-ARCHIVE add-on from 1 June 2026 onwards, we no longer use it.
Also, Priya mentioned you'd credit us 120.00 for the April outage, ref QS-OUT-4. Thanks!"""


def test_email_statements_are_tied_to_the_vendor_by_domain():
    data = {
        "cancellations": [
            {
                "sku": "QS-ARCHIVE",
                "effective": "2026-06-01",
                "quote": "please stop the QS-ARCHIVE add-on from 1 June 2026 onwards",
            }
        ],
        "credit_promises": [
            {"ref": "QS-OUT-4", "amount": "120.00", "quote": "credit us 120.00 for the April"}
        ],
        "references": [],
    }
    to = ("rhea@quillstack.test",)
    email = Document("b/2", "email", "m", EMAIL, date(2026, 5, 2), "ap@acme.test", to)
    x = facts_from_model(email, data, {"quillstack.test": "Quillstack"})
    assert x.cancellations[0].vendor == "Quillstack"
    assert x.cancellations[0].requested_by == "ap@acme.test"
    assert x.cancellations[0].effective == date(2026, 6, 1)
    # the credit quote holds the amount but not the ref, so it is not trusted
    assert x.credits == [] and "'QS-OUT-4' not in its quote" in x.unread[0]


def test_email_statements_from_an_unknown_vendor_are_dropped():
    data = {"cancellations": [{"sku": "QS-ARCHIVE", "effective": "2026-06-01", "quote": "x"}]}
    x = facts_from_model(doc(EMAIL, "email"), data, {})
    assert x.cancellations == [] and "vendor unknown" in x.unread[0]


def test_schema_is_strict_everywhere():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        elif node.get("type") == "array":
            walk(node["items"])

    walk(SCHEMA)
