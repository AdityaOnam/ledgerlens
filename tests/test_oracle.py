"""The oracle: independent of Ledgerlens' readers and rules, and right on a hand-built world."""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import ledgerlens.evaluate.oracle as oracle_module
import ledgerlens.evaluate.world as world_module
from ledgerlens.evaluate.oracle import expected
from ledgerlens.evaluate.world import (
    Bill,
    Cancel,
    Contract,
    Credit,
    Line,
    Person,
    Sku,
    Vendor,
    World,
)

D = Decimal


def _imports(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_oracle_and_world_import_nothing_from_ledgerlens_but_the_world():
    for module in (oracle_module, world_module):
        ours = {n for n in _imports(module) if n.startswith("ledgerlens")}
        assert ours <= {"ledgerlens.evaluate.world"}, module.__name__


def month(m: int) -> tuple[date, date]:
    ends = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30}
    return date(2027, m, 1), date(2027, m, ends[m])


def line(sku: str, m: int, qty: int, price: str) -> Line:
    start, end = month(m)
    return Line(sku, sku, start, end, qty, D(price))


def bill(inv: str, m: int, *lines: Line, day: int = 1, **kw) -> Bill:
    return Bill(inv, date(2027, m, day), date(2027, m, day), list(lines), **kw)


def contract(true_up=False, auto_renew=True, end=date(2027, 8, 31), notice=60) -> Contract:
    return Contract(
        "OF-2026-500",
        date(2026, 12, 1),
        end,
        auto_renew,
        notice,
        true_up,
        None,
        (Sku("AB-PRO", "Pro seat", D("10.00"), 100), Sku("AB-SSO", "SSO", D("200.00"), 1)),
        date(2026, 11, 20),
    )


def world(*vendors: Vendor) -> World:
    p = Person("Meera Iyer", "VP Finance", "meera@kestrel-foods.com")
    ap = Person("AP Team", "Accounts Payable", "ap@kestrel-foods.com")
    return World(1, "Kestrel Foods Ltd.", "kestrel-foods.com", p, ap, list(vendors),
                 [date(2027, 3, 25), date(2027, 6, 25)])  # fmt: skip


def found(w: World) -> set[tuple]:
    return {(e.cls, e.invoice_id or e.ref, e.sku, str(e.amount), e.batch) for e in expected(w)}


def test_clean_vendor_with_a_far_renewal_has_nothing():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(end=date(2028, 6, 30)))
    v.bills = [bill(f"INV-{m}", m, line("AB-PRO", m, 100, "10.00")) for m in range(1, 7)]
    assert expected(world(v)) == []


def test_line_rules_in_order_and_amounts():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(end=date(2028, 6, 30)))
    v.bills = [
        bill("INV-1", 1, line("AB-PRO", 1, 100, "11.00"), line("AB-SSO", 1, 1, "200.00")),
        bill("INV-2", 2, line("AB-PRO", 2, 104, "12.00"), line("AB-SSO", 2, 1, "200.00")),
        bill("INV-3", 3, line("AB-PRO", 3, 100, "10.00"), line("AB-SSO", 3, 1, "200.00")),
        # a corrected copy of January, sent in May: a duplicate, not a price problem again
        bill("INV-1A", 5, line("AB-PRO", 1, 100, "11.00"), day=12),
    ]
    v.cancels = [Cancel("AB-SSO", date(2027, 3, 1), date(2027, 2, 14))]
    assert found(world(v)) == {
        ("price_over_contract", "INV-1", "AB-PRO", "100.00", "batch_01"),
        ("price_over_contract", "INV-2", "AB-PRO", "208.00", "batch_01"),
        ("seats_over_licensed", "INV-2", "AB-PRO", "40.00", "batch_01"),  # 4 x the lower $10
        ("billed_after_cancel", "INV-3", "AB-SSO", "200.00", "batch_01"),
        ("duplicate_charge", "INV-1A", "AB-PRO", "1100.00", "batch_02"),
    }


def test_true_up_makes_extra_seats_fine():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(true_up=True, end=date(2028, 6, 30)))
    v.bills = [bill("INV-1", 1, line("AB-PRO", 1, 130, "10.00"))]
    assert expected(world(v)) == []


def test_vendor_without_an_order_form_and_a_bad_total():
    v = Vendor("Cd Ltd.", "CD", "cd.io", True, None)
    v.bills = [bill("INV-9", 4, line("CD-USER", 4, 3, "20.00"), total_error=D("5.00"))]
    assert found(world(v)) == {
        ("cannot_determine", "INV-9", None, "65.00", "batch_02"),  # the printed total
        ("cannot_determine", "INV-9", None, "5.00", "batch_02"),  # the gap
    }


def test_credit_counts_only_after_its_grace_period_and_only_if_never_applied():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(end=date(2028, 6, 30)))
    v.credits = [
        Credit("CR-1", D("150.00"), date(2027, 1, 10)),  # due 11 Mar: missing in batch_01
        Credit("CR-2", D("75.00"), date(2027, 2, 10)),  # due 11 Apr: applied in April
        Credit("CR-3", D("90.00"), date(2027, 5, 10)),  # due 9 Jul: not yet due at the end
    ]
    v.bills = [bill("INV-4", 4, line("AB-PRO", 4, 100, "10.00"), credits=[("CR-2", D("75.00"))])]
    assert found(world(v)) == {("credit_not_applied", "CR-1", None, "150.00", "batch_01")}


def test_renewal_window_value_excludes_cancelled_skus():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(end=date(2027, 8, 31), notice=60))
    v.cancels = [Cancel("AB-SSO", date(2027, 5, 1), date(2027, 4, 12))]
    # deadline 2 Jul 2027 falls within 45 days of 25 Jun, not of 25 Mar
    assert found(world(v)) == {("renewal_notice_due", "OF-2026-500", None, "12000.00", "batch_02")}


def test_no_renewal_finding_without_auto_renewal():
    v = Vendor("Ab Inc.", "AB", "ab.io", False, contract(auto_renew=False, end=date(2027, 8, 31)))
    assert expected(world(v)) == []
