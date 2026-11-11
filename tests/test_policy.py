from decimal import Decimal

import pytest

from ledgerlens.decide.policy import Mode, decide
from ledgerlens.domain.models import Action, Finding, FindingClass


def f(cls, amount):
    return Finding(cls, "V", "s", Decimal(amount), [])


@pytest.mark.parametrize("cls", list(FindingClass))
@pytest.mark.parametrize("amount", ["0.01", "2499.99", "2500.00", "90000"])
def test_supervised_never_executes(cls, amount):
    assert decide(f(cls, amount), Mode.SUPERVISED).executed is False


@pytest.mark.parametrize("cls", list(FindingClass))
def test_at_threshold_money_actions_go_to_a_person(cls):
    out = decide(f(cls, "2500.00"), Mode.AUTONOMOUS)
    if cls is FindingClass.CANNOT_DETERMINE:
        assert out.action is Action.REQUEST_DOCUMENT
    else:
        assert out.action is Action.HUMAN_REVIEW and not out.executed


def test_conflict_and_renewal_never_execute():
    for cls in (FindingClass.CONFLICT, FindingClass.RENEWAL_NOTICE_DUE):
        assert decide(f(cls, "1.00"), Mode.AUTONOMOUS).executed is False


def test_small_dispute_executes_in_autonomous():
    out = decide(f(FindingClass.DUPLICATE_CHARGE, "860.00"), Mode.AUTONOMOUS)
    assert out.action is Action.DISPUTE and out.executed
