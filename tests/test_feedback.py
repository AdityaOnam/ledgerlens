"""Reviewers' answers: which ones are accepted, and which later findings they govern."""

from datetime import date
from decimal import Decimal

import pytest

from ledgerlens.decide import feedback
from ledgerlens.decide.feedback import FeedbackError
from ledgerlens.decide.policy import Mode, decide
from ledgerlens.domain.models import Action, Answer, Finding, FindingClass, Scope
from ledgerlens.store import decisions as decision_log
from ledgerlens.store.memory import Memory

C = FindingClass
ON = date(2026, 3, 1)


def finding(cls=C.SEATS_OVER_LICENSED, amount="456.00", invoice="INV-1", **details):
    return Finding(
        cls, "Vendo", "s", Decimal(amount), [], invoice_id=invoice, sku="VN-SEAT",
        rule="r", details={"period": "2026-01", **details},
    )  # fmt: skip


def conflict(invoice="INV-1"):
    return finding(C.CONFLICT, "20.00", invoice, candidates=["10.00", "8.00"])


def decided(f, ans, scope=Scope.ONCE, **kw):
    return feedback.answer(feedback.record(f, "batch_01"), ans, scope, "Ada Finch", ON, **kw)


def test_record_keeps_what_a_reviewer_needs():
    rec = feedback.record(conflict(), "batch_02")
    assert rec.id == conflict().id and len(rec.id) == 8 and rec.key == conflict().key
    assert rec.candidates == (Decimal("10.00"), Decimal("8.00")) and rec.batch == "batch_02"


def test_the_id_is_stable_and_follows_the_key():
    assert finding().id == finding().id
    assert finding().id != finding(invoice="INV-2").id


def test_standing_decision_is_capped_at_the_answered_amount_by_default():
    d = decided(finding(), Answer.DISMISS, Scope.STANDING)
    assert d.up_to == Decimal("456.00") and d.standing and d.active
    assert decided(finding(), Answer.DISMISS, Scope.STANDING, up_to=Decimal(900)).up_to == 900


def test_one_off_decision_has_no_cap():
    assert decided(finding(), Answer.DISMISS).up_to is None
    with pytest.raises(FeedbackError, match="standing"):
        decided(finding(), Answer.DISMISS, up_to=Decimal(1))


@pytest.mark.parametrize(
    "f, ans, scope, kw, match",
    [
        (finding(), Answer.PRICE, Scope.ONCE, {"price": Decimal(1)}, "only settle a conflict"),
        (conflict(), Answer.PRICE, Scope.ONCE, {}, "name the price"),
        (conflict(), Answer.PRICE, Scope.ONCE, {"price": Decimal(9)}, "not one of the prices"),
        (conflict(), Answer.DISMISS, Scope.ONCE, {"price": Decimal(8)}, "goes with the 'price'"),
        (conflict(), Answer.APPROVE, Scope.STANDING, {}, "cannot be approved standing"),
        (finding(C.RENEWAL_NOTICE_DUE), Answer.APPROVE, Scope.STANDING, {}, "approved standing"),
    ],
)
def test_answers_that_do_not_fit_are_refused(f, ans, scope, kw, match):
    with pytest.raises(FeedbackError, match=match):
        decided(f, ans, scope, **kw)


def test_reviewer_must_be_named():
    with pytest.raises(FeedbackError, match="who decided"):
        feedback.answer(feedback.record(finding(), "b"), Answer.DISMISS, Scope.ONCE, " ", ON)


def test_price_answer_is_one_of_the_candidates_in_cents():
    d = decided(conflict(), Answer.PRICE, Scope.STANDING, price=Decimal("8"))
    assert d.price == Decimal("8.00") and d.up_to is None


def test_one_off_applies_to_the_same_finding_only():
    d = decided(finding(), Answer.DISMISS)
    assert feedback.lookup(finding(), [d]).decision == d
    assert feedback.lookup(finding(invoice="INV-2"), [d]).decision is None


def test_standing_applies_to_later_findings_of_the_same_kind():
    d = decided(finding(), Answer.DISMISS, Scope.STANDING)
    assert feedback.lookup(finding(invoice="INV-2"), [d]).decision == d
    other_class = finding(C.PRICE_OVER_CONTRACT, invoice="INV-2")
    assert feedback.lookup(other_class, [d]).decision is None


def test_standing_never_covers_a_bigger_amount_and_says_so():
    d = decided(finding(), Answer.DISMISS, Scope.STANDING)
    applied = feedback.lookup(finding(amount="456.01", invoice="INV-2"), [d])
    assert applied.decision is None
    assert "covers up to $456.00" in applied.note and "$456.01" in applied.note


def test_the_latest_decision_wins_and_revoked_ones_stop_applying():
    first = decided(finding(), Answer.DISMISS, Scope.STANDING)
    second = decided(finding(), Answer.APPROVE, Scope.STANDING)
    later = finding(invoice="INV-2")
    assert feedback.lookup(later, [first, second]).decision == second
    log = feedback.revoke([first, second], finding().id, date(2026, 4, 1))
    assert all(d.revoked_on == date(2026, 4, 1) for d in log)
    assert feedback.lookup(later, log).decision is None
    with pytest.raises(FeedbackError, match="no active decision"):
        feedback.revoke(log, finding().id, ON)


def test_price_decisions_are_rulings_not_lookups():
    d = decided(conflict(), Answer.PRICE, price=Decimal("8.00"))
    assert feedback.lookup(conflict(), [d]).decision is None
    assert feedback.rulings([d]) == [d]


def test_approved_finding_skips_the_threshold_but_supervised_still_executes_nothing():
    big = finding(amount="9000.00", approved_by="once approve by Ada")
    assert decide(big, Mode.AUTONOMOUS).action is Action.DISPUTE and big.executed
    assert decide(finding(amount="9000.00"), Mode.AUTONOMOUS).action is Action.HUMAN_REVIEW
    assert not decide(finding(amount="9000.00", approved_by="x"), Mode.SUPERVISED).executed


def test_approved_conflict_is_disputed_and_renewal_is_never_sent_automatically():
    c = conflict()
    c.details["approved_by"] = "once approve by Ada"
    assert decide(c, Mode.AUTONOMOUS).action is Action.DISPUTE and c.executed
    r = finding(C.RENEWAL_NOTICE_DUE, approved_by="once approve by Ada")
    assert decide(r, Mode.AUTONOMOUS).action is Action.SEND_NOTICE and not r.executed


def test_decision_log_and_finding_records_round_trip(tmp_path):
    log = [
        decided(finding(), Answer.DISMISS, Scope.STANDING, note="vendor credit agreed"),
        decided(conflict(), Answer.PRICE, price=Decimal("8.00")),
    ]
    log = feedback.revoke(log, finding().id, date(2026, 4, 1))
    path = tmp_path / decision_log.FILENAME
    decision_log.save(path, log)
    again = decision_log.load(path)
    assert again == log and again[0].answer is Answer.DISMISS and again[1].scope is Scope.ONCE
    assert decision_log.load(tmp_path / "none.json") == []

    mem = Memory(findings={conflict().id: feedback.record(conflict(), "batch_01")})
    mem.save(tmp_path / "memory.json")
    assert Memory.load(tmp_path / "memory.json").findings == mem.findings
