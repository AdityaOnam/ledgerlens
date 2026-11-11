"""What Ledgerlens remembers between batches, kept as one JSON file per state directory.

Facts are only ever added; a later document never erases an earlier one. Rules decide which
fact wins (e.g. an amendment over its order form), so the history stays auditable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ledgerlens.domain.models import (
    Agreement,
    Cancellation,
    CreditPromise,
    DocumentReference,
    Invoice,
)
from ledgerlens.ingest.extract import Extraction
from ledgerlens.store.codec import decode, encode

FACT_TYPES = {
    "agreements": Agreement,
    "invoices": Invoice,
    "cancellations": Cancellation,
    "credits": CreditPromise,
    "references": DocumentReference,
}


@dataclass
class Memory:
    agreements: list[Agreement] = field(default_factory=list)
    invoices: list[Invoice] = field(default_factory=list)
    cancellations: list[Cancellation] = field(default_factory=list)
    credits: list[CreditPromise] = field(default_factory=list)
    references: list[DocumentReference] = field(default_factory=list)
    vendor_domains: dict[str, str] = field(default_factory=dict)
    batches: list[str] = field(default_factory=list)
    reported: dict[str, str] = field(default_factory=dict)  # finding key -> batch first reported

    def absorb(self, batch: str, x: Extraction) -> None:
        """Add a batch's facts, skipping exact repeats (a forwarded copy of the same invoice)."""
        for name in FACT_TYPES:
            have = getattr(self, name)
            for fact in getattr(x, name):
                if fact not in have:
                    have.append(fact)
        self.vendor_domains.update(x.vendor_domains)
        if batch not in self.batches:
            self.batches.append(batch)

    # --- persistence --------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> Memory:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        mem = cls(vendor_domains=raw.get("vendor_domains", {}), batches=raw.get("batches", []),
                  reported=raw.get("reported", {}))
        for name, tp in FACT_TYPES.items():
            setattr(mem, name, [decode(tp, d) for d in raw.get(name, [])])
        return mem

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: encode(getattr(self, name)) for name in FACT_TYPES}
        data |= {"vendor_domains": self.vendor_domains, "batches": self.batches,
                 "reported": self.reported}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
