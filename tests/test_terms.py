from datetime import date
from decimal import Decimal

from ledgerlens.domain.models import Agreement, Evidence, PriceStatement, PriceTerm
from ledgerlens.rules.authority import Authority, Signatory
from ledgerlens.rules.terms import LATER_EMAIL, SAME_DAY_EMAILS, resolve

EV = Evidence("d", "q")


def base(**kw):
    args = dict(
        agreement_id="OF-1",
        vendor="V",
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
        auto_renew=True,
        notice_days=30,
        uplift_cap=Decimal("0.05"),
        true_up_allowed=False,
        prices=(PriceTerm("S-1", "seat", Decimal("10.00"), 5, EV),),
        evidence=EV,
    )
    args.update(kw)
    return Agreement(**args)


def amend(ref, price, effective, signed_by="", qty=5):
    return Agreement(
        ref,
        "V",
        effective,
        date(2025, 12, 31),
        False,
        0,
        None,
        False,
        (PriceTerm("S-1", "seat", Decimal(price), qty, EV),),
        EV,
        amends="OF-1",
        effective=effective,
        signed_by=signed_by,
    )


def test_inside_term_uses_agreed_price():
    r = resolve([base()], "V", "S-1", date(2025, 6, 1))
    assert (r.status, r.price) == ("agreed", Decimal("10.00"))


def test_cap_compounds_per_renewal_year():
    r = resolve([base()], "V", "S-1", date(2027, 2, 1))
    assert (r.status, r.renewal_years, r.price) == ("renewal", 2, Decimal("11.03"))


def test_no_auto_renew_means_no_agreement_after_end():
    assert resolve([base(auto_renew=False)], "V", "S-1", date(2026, 1, 5)).status == "none"


def test_renewal_without_cap_is_unpriced_but_keeps_seat_limit():
    r = resolve([base(uplift_cap=None)], "V", "S-1", date(2026, 2, 1))
    assert (r.status, r.price, r.licensed_qty) == ("unpriced", None, 5)


def test_latest_amendment_wins():
    docs = [
        base(),
        amend("AM-1", "9.00", date(2025, 3, 1)),
        amend("AM-2", "8.00", date(2025, 6, 1)),
    ]
    assert resolve(docs, "V", "S-1", date(2025, 4, 1)).price == Decimal("9.00")
    assert resolve(docs, "V", "S-1", date(2025, 7, 1)).price == Decimal("8.00")


def test_same_day_amendments_that_disagree_are_a_conflict():
    docs = [
        base(),
        amend("AM-1", "9.00", date(2025, 3, 1)),
        amend("AM-2", "8.50", date(2025, 3, 1)),
    ]
    r = resolve(docs, "V", "S-1", date(2025, 4, 1))
    assert r.status == "conflict" and {t.price for t in r.candidates} == {
        Decimal("9.00"),
        Decimal("8.50"),
    }


def email(price, effective, agreed_by="cfo@acme.test", doc="mail/1"):
    return PriceStatement(
        "V", "S-1", Decimal(price), effective, agreed_by, Evidence(doc, f"price ${price}")
    )


AUTH = Authority((Signatory("Ada Finch", "cfo@acme.test"),))


def test_later_email_that_disagrees_with_the_order_form_is_a_conflict():
    r = resolve([base()], "V", "S-1", date(2025, 8, 1), [email("9.00", date(2025, 7, 1))])
    assert (r.status, r.reason) == ("conflict", LATER_EMAIL)
    assert [(t.source, t.price) for t in r.candidates] == [
        ("order form", Decimal("10.00")),
        ("email", Decimal("9.00")),
    ]


def test_later_email_that_agrees_changes_nothing():
    r = resolve([base()], "V", "S-1", date(2025, 8, 1), [email("10.00", date(2025, 7, 1))])
    assert (r.status, r.price) == ("agreed", Decimal("10.00"))


def test_signed_amendment_supersedes_an_earlier_email():
    docs = [base(), amend("AM-1", "9.50", date(2025, 6, 1))]
    emails = [email("9.00", date(2025, 3, 1))]
    r = resolve(docs, "V", "S-1", date(2025, 8, 1), emails)
    assert (r.status, r.price) == ("agreed", Decimal("9.50"))


def test_amendment_beats_an_email_effective_the_same_day():
    docs = [base(), amend("AM-1", "9.50", date(2025, 6, 1))]
    r = resolve(docs, "V", "S-1", date(2025, 8, 1), [email("9.00", date(2025, 6, 1))])
    assert r.price == Decimal("9.50")


def test_email_in_the_future_is_not_yet_in_force():
    r = resolve([base()], "V", "S-1", date(2025, 8, 1), [email("9.00", date(2025, 9, 1))])
    assert r.status == "agreed"


def test_email_alone_prices_a_sku_no_document_covers():
    r = resolve([], "V", "S-1", date(2025, 8, 1), [email("9.00", date(2025, 7, 1))])
    assert (r.status, r.price, r.licensed_qty) == ("agreed", Decimal("9.00"), None)
    emails = [email("9.00", date(2025, 7, 1)), email("8.00", date(2025, 7, 1), doc="mail/2")]
    assert resolve([], "V", "S-1", date(2025, 8, 1), emails).reason == SAME_DAY_EMAILS


def test_email_after_a_capped_renewal_is_compared_with_the_ceiling():
    on = date(2026, 2, 1)  # renewal year 1: ceiling 10.50
    ok = resolve([base()], "V", "S-1", on, [email("10.50", date(2026, 1, 1))])
    assert (ok.status, ok.price) == ("renewal", Decimal("10.50"))
    clash = resolve([base()], "V", "S-1", on, [email("10.20", date(2026, 1, 1))])
    assert clash.status == "conflict" and clash.candidates[0].price == Decimal("10.50")


def test_email_sets_the_price_after_an_uncapped_renewal():
    r = resolve(
        [base(uplift_cap=None)], "V", "S-1", date(2026, 2, 1), [email("11.00", date(2026, 1, 1))]
    )
    assert (r.status, r.price, r.licensed_qty) == ("agreed", Decimal("11.00"), 5)


def test_without_authority_terms_from_anyone_bind():
    docs = [base(), amend("AM-1", "12.00", date(2025, 3, 1), signed_by="Dev Malhotra")]
    r = resolve(docs, "V", "S-1", date(2025, 4, 1))
    assert r.price == Decimal("12.00") and r.unauthorised == []


def test_unauthorised_amendment_and_email_do_not_bind():
    docs = [
        base(signed_by="Ada Finch, CFO"),
        amend("AM-1", "12.00", date(2025, 3, 1), signed_by="Dev Malhotra", qty=8),
    ]
    emails = [email("9.00", date(2025, 3, 1), agreed_by="dev@acme.test")]
    r = resolve(docs, "V", "S-1", date(2025, 4, 1), emails, AUTH)
    assert (r.status, r.price, r.licensed_qty) == ("agreed", Decimal("10.00"), 5)
    assert sorted((t.source, t.party) for t in r.unauthorised) == [
        ("amendment", "Dev Malhotra"),
        ("email", "dev@acme.test"),
    ]


def test_authorised_amendment_binds_with_authority():
    docs = [
        base(signed_by="Ada Finch, CFO"),
        amend("AM-1", "9.00", date(2025, 3, 1), signed_by="Ada Finch"),
    ]
    assert resolve(docs, "V", "S-1", date(2025, 4, 1), (), AUTH).price == Decimal("9.00")


def test_unsigned_order_form_binds_nobody_under_authority():
    r = resolve([base()], "V", "S-1", date(2025, 4, 1), (), AUTH)
    assert r.status == "none" and [t.ref for t in r.unauthorised] == ["OF-1"]
