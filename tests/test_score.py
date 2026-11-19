"""Scoring findings against the oracle: matching, precision, recall and dollars."""

from decimal import Decimal

from ledgerlens.domain.models import Evidence, Finding, FindingClass
from ledgerlens.evaluate.oracle import Expected
from ledgerlens.evaluate.score import Score, score

D = Decimal
EV = [Evidence("doc", "quote")]


def exp(cls, inv, amount, sku="AB-PRO", ref=""):
    return Expected(cls, "Ab Inc.", inv, sku, ref, D(amount), "why", "batch_01")


def fnd(cls, inv, amount, sku="AB-PRO", ref=None):
    details = {"ref": ref} if ref else {}
    return Finding(FindingClass(cls), "Ab Inc.", "s", D(amount), EV, inv, sku, details=details)


def test_perfect_match():
    s = score(
        [fnd("price_over_contract", "INV-1", "100.00")],
        [exp("price_over_contract", "INV-1", "100.00")],
    )
    assert (s.tp, s.fp, s.fn, s.precision, s.recall) == (1, 0, 0, 1.0, 1.0)
    assert s.at_stake == s.recovered == D("100.00") and s.wrongly_claimed == 0


def test_missed_false_and_overclaimed():
    s = score(
        [
            fnd("price_over_contract", "INV-1", "130.00"),  # matched, $30 too much
            fnd("duplicate_charge", "INV-2", "500.00"),  # not owed at all
            fnd("seats_over_licensed", "INV-3", "20.00"),  # matched, $20 too little
        ],
        [
            exp("price_over_contract", "INV-1", "100.00"),
            exp("seats_over_licensed", "INV-3", "40.00"),
            exp("billed_after_cancel", "INV-4", "200.00", sku="AB-SSO"),  # missed
        ],
    )
    assert (s.tp, s.fp, s.fn) == (2, 1, 1)
    assert s.precision == 2 / 3 and s.recall == 2 / 3
    assert len(s.wrong_amounts) == 2
    assert s.at_stake == D("340.00")
    assert s.recovered == D("120.00")
    assert s.wrongly_claimed == D("530.00")
    assert s.by_class() == {
        "billed_after_cancel": (0, 0, 1),
        "duplicate_charge": (0, 1, 0),
        "price_over_contract": (1, 0, 0),
        "seats_over_licensed": (1, 0, 0),
    }


def test_only_money_classes_count_towards_dollars():
    s = score(
        [fnd("renewal_notice_due", None, "90000.00", sku=None, ref="OF-1")],
        [
            exp("renewal_notice_due", None, "90000.00", sku=None, ref="OF-1"),
            exp("cannot_determine", "INV-9", "65.00", sku=None),
        ],
    )
    assert (s.tp, s.fn) == (1, 1)
    assert s.at_stake == s.recovered == s.wrongly_claimed == 0


def test_ref_distinguishes_findings_on_the_same_invoice():
    found = [
        fnd("cannot_determine", "INV-9", "5.00", sku=None, ref="total"),
        fnd("cannot_determine", "INV-9", "65.00", sku=None),
    ]
    s = score(
        found,
        [
            exp("cannot_determine", "INV-9", "65.00", sku=None),
            exp("cannot_determine", "INV-9", "5.00", sku=None, ref="total"),
        ],
    )
    assert s.tp == 2 and not s.wrong_amounts


def test_empty_is_perfect_and_scores_add_up():
    assert Score().precision == Score().recall == 1.0
    a = score([], [exp("price_over_contract", "INV-1", "1.00")])
    b = score([fnd("price_over_contract", "INV-2", "1.00")], [])
    total = a + b
    assert (total.tp, total.fp, total.fn) == (0, 1, 1)
