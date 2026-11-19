"""Compare an audit's findings with the oracle's expected findings.

A finding matches an expected one when class, vendor, invoice, SKU and reference agree; its
amount may still differ, and the dollar figures say by how much. Only the classes that claim
money back from a vendor count towards dollars:

- at stake: what the oracle says is owed back;
- recovered: what the audit claimed of it (a matched finding counts up to the expected amount);
- wrongly claimed: what the audit claimed that is not owed, from false findings and from
  matched findings that ask for more than is owed. This is the number that must stay at zero
  before anything is disputed unattended.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from ledgerlens.domain.models import Finding
from ledgerlens.evaluate.oracle import Expected
from ledgerlens.report.render import RECOVERABLE

MONEY_CLASSES = {str(c) for c in RECOVERABLE}


def finding_key(f: Finding) -> tuple[str, str, str, str, str]:
    return (str(f.cls), f.vendor, f.invoice_id or "", f.sku or "", str(f.details.get("ref", "")))


@dataclass
class Score:
    matched: list[tuple[Expected, Finding]] = field(default_factory=list)
    missed: list[Expected] = field(default_factory=list)
    spurious: list[Finding] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return len(self.matched)

    @property
    def fp(self) -> int:
        return len(self.spurious)

    @property
    def fn(self) -> int:
        return len(self.missed)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def wrong_amounts(self) -> list[tuple[Expected, Finding]]:
        return [(e, f) for e, f in self.matched if e.amount != f.amount]

    @property
    def at_stake(self) -> Decimal:
        return sum(
            (e.amount for e in [*(e for e, _ in self.matched), *self.missed]
             if e.cls in MONEY_CLASSES),
            Decimal(0),
        )  # fmt: skip

    @property
    def recovered(self) -> Decimal:
        return sum(
            (min(e.amount, f.amount) for e, f in self.matched if e.cls in MONEY_CLASSES),
            Decimal(0),
        )

    @property
    def wrongly_claimed(self) -> Decimal:
        false = sum((f.amount for f in self.spurious if str(f.cls) in MONEY_CLASSES), Decimal(0))
        over = sum(
            (max(f.amount - e.amount, Decimal(0)) for e, f in self.matched
             if e.cls in MONEY_CLASSES),
            Decimal(0),
        )  # fmt: skip
        return false + over

    def by_class(self) -> dict[str, tuple[int, int, int]]:
        """class -> (true positives, false positives, false negatives)."""
        tp = Counter(e.cls for e, _ in self.matched)
        fp = Counter(str(f.cls) for f in self.spurious)
        fn = Counter(e.cls for e in self.missed)
        return {c: (tp[c], fp[c], fn[c]) for c in sorted({*tp, *fp, *fn})}

    def __add__(self, other: Score) -> Score:
        return Score(
            [*self.matched, *other.matched],
            [*self.missed, *other.missed],
            [*self.spurious, *other.spurious],
        )


def score(found: list[Finding], expected: list[Expected]) -> Score:
    """Pair findings with expected findings by key; leftovers on either side are errors."""
    pending: dict[tuple[str, str, str, str, str], list[Expected]] = defaultdict(list)
    for e in expected:
        pending[e.key].append(e)
    out = Score()
    for f in found:
        bucket = pending.get(finding_key(f))
        if bucket:
            out.matched.append((bucket.pop(0), f))
        else:
            out.spurious.append(f)
    out.missed = [e for bucket in pending.values() for e in bucket]
    return out
