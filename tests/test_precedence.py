"""Detectors over several sources: precedence, authority and documents cited but never received."""

from datetime import date
from decimal import Decimal

from ledgerlens.decide.policy import Mode, decide
from ledgerlens.domain.models import (
    Action,
    Agreement,
    DocumentReference,
    Evidence,
    Invoice,
    InvoiceLine,
    PriceStatement,
    PriceTerm,
)
from ledgerlens.rules.authority import Authority, Signatory
from ledgerlens.rules.detectors import detect
from ledgerlens.store.memory import Memory

AUTH = Authority((Signatory("Ada Finch", "ada@acme.test"),))
AS_OF = date(2026, 6, 15)


def ev(doc, quote="quoted line"):
    return Evidence(doc, quote)


def order_form(signed_by="Ada Finch, CFO"):
    return Agreement(
        "OF-2026-001", "Vendo", date(2026, 1, 1), date(2026, 12, 31), False, 0, None, False,
        (PriceTerm("VN-SEAT", "seat", Decimal("10.00"), 5, ev("of")),), ev("of"),
        signed_by=signed_by,
    )  # fmt: skip


def amendment(price, qty, signed_by):
    return Agreement(
        "AM-2026-002", "Vendo", date(2026, 3, 1), date(2026, 12, 31), False, 0, None, False,
        (PriceTerm("VN-SEAT", "seat", Decimal(price), qty, ev("am")),), ev("am"),
        amends="OF-2026-001", effective=date(2026, 3, 1), signed_by=signed_by,
    )  # fmt: skip


def invoice(unit, qty, inv_id="INV-1"):
    amount = Decimal(unit) * qty
    line = InvoiceLine("VN-SEAT", "seat", date(2026, 5, 1), date(2026, 5, 31), qty,
                       Decimal(unit), amount, ev(inv_id, "line"))  # fmt: skip
    return Invoice(inv_id, "Vendo", date(2026, 5, 1), date(2026, 5, 31), (line,), (), amount,
                   ev(inv_id))  # fmt: skip


def email_price(price, agreed_by="ada@acme.test"):
    return PriceStatement("Vendo", "VN-SEAT", Decimal(price), date(2026, 4, 1), agreed_by,
                          ev("mail", f"the price for VN-SEAT will be ${price}"))  # fmt: skip


def found(mem, authority=AUTH):
    return [(str(f.cls), f.rule, str(f.amount)) for f in detect(mem, AS_OF, authority)]


def test_later_email_against_the_order_form_goes_to_a_person():
    mem = Memory(agreements=[order_form()], invoices=[invoice("10.00", 5)])
    mem.prices = [email_price("8.00")]
    (f,) = detect(mem, AS_OF, AUTH)
    assert (str(f.cls), f.rule, f.amount) == (
        "conflict",
        "later_email_disagrees_with_signed_terms",
        Decimal("10.00"),
    )
    assert f.details["sources"][0] == "order form OF-2026-001"
    assert "email of 2026-04-01 agreed by ada@acme.test" in f.summary
    assert [e.doc_id for e in f.evidence] == ["INV-1", "of", "mail"]
    assert decide(f, Mode.AUTONOMOUS).action is Action.HUMAN_REVIEW and not f.executed


def test_conflict_that_costs_nothing_is_not_reported():
    mem = Memory(agreements=[order_form()], invoices=[invoice("8.00", 5)])
    mem.prices = [email_price("8.00")]
    assert found(mem) == []


def test_invoice_following_an_unauthorised_amendment_cannot_be_determined():
    mem = Memory(
        agreements=[order_form(), amendment("12.00", 7, "Dev Malhotra, Engineering Manager")],
        invoices=[invoice("12.00", 7)],
    )
    (f,) = detect(mem, AS_OF, AUTH)
    assert (str(f.cls), f.rule) == ("cannot_determine", "term_agreed_without_authority")
    assert f.amount == Decimal("34.00")  # 7 x 12.00 billed, 5 x 10.00 binding
    assert f.details["holder"] == "ada@acme.test" and f.details["ref"] == "AM-2026-002"
    assert "Dev Malhotra" in f.summary and f.evidence[1].doc_id == "am"
    assert decide(f, Mode.AUTONOMOUS).action is Action.REQUEST_DOCUMENT


def test_without_an_authority_file_the_same_amendment_simply_binds():
    mem = Memory(
        agreements=[order_form(), amendment("12.00", 7, "Dev Malhotra, Engineering Manager")],
        invoices=[invoice("12.00", 7)],
    )
    assert found(mem, None) == []


def test_unauthorised_seat_increase_is_not_disputed_as_overage():
    mem = Memory(
        agreements=[order_form(), amendment("10.00", 8, "Dev Malhotra")],
        invoices=[invoice("10.00", 8)],
    )
    assert found(mem) == [("cannot_determine", "term_agreed_without_authority", "30.00")]


def test_invoice_ignoring_an_unauthorised_discount_is_fine():
    mem = Memory(agreements=[order_form()], invoices=[invoice("10.00", 5)])
    mem.prices = [email_price("8.00", agreed_by="dev@acme.test")]
    assert found(mem) == []


def test_overcharge_unrelated_to_the_unauthorised_term_is_still_disputed():
    mem = Memory(
        agreements=[order_form(), amendment("12.00", 5, "Dev Malhotra")],
        invoices=[invoice("11.00", 5)],
    )
    assert found(mem) == [("price_over_contract", "unit_price_above_agreed", "5.00")]


def test_unauthorised_order_form_alone_puts_the_whole_line_at_stake():
    mem = Memory(agreements=[order_form(signed_by="")], invoices=[invoice("10.00", 5)])
    assert found(mem) == [("cannot_determine", "term_agreed_without_authority", "50.00")]


def cited(ref="AM-2026-009"):
    return DocumentReference("Vendo", ref, "amendment", "ar@vendo.test",
                             ev("cover", f"reflects amendment {ref}"))  # fmt: skip


def test_overcharge_with_a_cited_but_missing_amendment_cannot_be_determined():
    mem = Memory(agreements=[order_form()], invoices=[invoice("12.00", 5)])
    mem.references = [cited()]
    (f,) = detect(mem, AS_OF, AUTH)
    assert (str(f.cls), f.rule, f.amount) == (
        "cannot_determine",
        "cited_document_missing",
        Decimal("10.00"),
    )
    assert (f.details["missing"], f.details["holder"]) == ("AM-2026-009", "ar@vendo.test")


def test_missing_document_does_not_matter_when_the_line_is_within_terms():
    mem = Memory(agreements=[order_form()], invoices=[invoice("10.00", 5)])
    mem.references = [cited()]
    assert found(mem) == []


def test_a_cited_document_that_is_on_file_is_not_missing():
    mem = Memory(agreements=[order_form()], invoices=[invoice("12.00", 5)])
    mem.references = [cited("OF-2026-001")]
    assert found(mem) == [("price_over_contract", "unit_price_above_agreed", "10.00")]
