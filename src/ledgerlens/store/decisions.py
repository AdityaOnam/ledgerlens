"""Reviewers' decisions, kept in their own JSON file next to the memory.

They are kept apart from ``memory.json`` because they are knowledge a person supplied, not facts
read from the mailbox: ``ledgerlens audit --reset`` forgets the batches but keeps the decisions,
so a mailbox audited again from scratch is answered the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

from ledgerlens.domain.models import Decision
from ledgerlens.store.codec import decode, encode

FILENAME = "decisions.json"


def load(path: Path) -> list[Decision]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [decode(Decision, d) for d in raw.get("decisions", [])]


def save(path: Path, decisions: list[Decision]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    data = {"decisions": encode(decisions)}
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
