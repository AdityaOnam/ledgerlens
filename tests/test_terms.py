from datetime import date
from decimal import Decimal

from ledgerlens.domain.models import Agreement, Evidence, PriceTerm
from ledgerlens.rules.terms import resolve

EV = Evidence("d", "q")


def base(**kw):
    args = dict(agreement_id="OF-1", vendor="V", start=date(2025, 1, 1), end=date(2025, 12, 31),
                auto_renew=True, notice_days=30, uplift_cap=Decimal("0.05"),
                true_up_allowed=False, prices=(PriceTerm("S-1", "seat", Decimal("10.00"), 5, EV),),
                evidence=EV)
    args.update(kw)
    return Agreement(**args)


def amend(ref, price, effective):
    return Agreement(ref, "V", effective, date(2025, 12, 31), False, 0, None, False,
                     (PriceTerm("S-1", "seat", Decimal(price), 5, EV),), EV, amends="OF-1",
                     effective=effective)


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
    docs = [base(), amend("AM-1", "9.00", date(2025, 3, 1)), amend("AM-2", "8.00", date(2025, 6, 1))]
    assert resolve(docs, "V", "S-1", date(2025, 4, 1)).price == Decimal("9.00")
    assert resolve(docs, "V", "S-1", date(2025, 7, 1)).price == Decimal("8.00")


def test_same_day_amendments_that_disagree_are_a_conflict():
    docs = [base(), amend("AM-1", "9.00", date(2025, 3, 1)), amend("AM-2", "8.50", date(2025, 3, 1))]
    r = resolve(docs, "V", "S-1", date(2025, 4, 1))
    assert r.status == "conflict" and {p for p, _ in r.candidates} == {Decimal("9.00"), Decimal("8.50")}
