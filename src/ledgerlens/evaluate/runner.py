"""Generate a synthetic mailbox per seed, audit it, score it against the oracle, report.

The audit is the real one (``app.run``): mailbox reader, extractor, memory, detectors and policy,
batch by batch. Only the documents are synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path

from ledgerlens.app import run
from ledgerlens.decide.policy import Mode
from ledgerlens.evaluate.oracle import Expected, expected
from ledgerlens.evaluate.score import Score, score
from ledgerlens.evaluate.synth import generate, write_mailbox
from ledgerlens.ingest.extract import Extractor, extract


@dataclass
class Scenario:
    seed: int
    company: str
    vendors: int
    documents: int
    score: Score
    notes: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    scenarios: list[Scenario]
    extractor: str = "layout reader"

    @property
    def total(self) -> Score:
        return reduce(lambda a, b: a + b, (s.score for s in self.scenarios), Score())


def parse_seeds(text: str) -> list[int]:
    """'7', '1-20' or '1,4,9-12' -> a list of seeds."""
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            low, high = (int(x) for x in part.split("-", 1))
            if high < low:
                raise ValueError(f"empty seed range: {part}")
            seeds.extend(range(low, high + 1))
        elif part:
            seeds.append(int(part))
    if not seeds:
        raise ValueError("no seeds given")
    return seeds


def evaluate(
    seeds: Iterable[int],
    work: Path,
    vendors: int = 6,
    months: int = 6,
    batches: int = 2,
    extractor: Extractor = extract,
    described: str = "layout reader",
) -> Evaluation:
    """Audit one synthetic mailbox per seed under ``work/seed_N`` (mailbox and state)."""
    scenarios = []
    for seed in seeds:
        world = generate(seed, vendors, months, batches)
        root = work / f"seed_{seed}"
        written = write_mailbox(world, root / "mailbox")
        results = run(root / "mailbox", root / "state", Mode.SUPERVISED, extractor=extractor)
        found = [f for r in results for f in r.findings]
        notes = [n for r in results for n in r.notes]
        scenarios.append(
            Scenario(
                seed,
                world.company,
                len(world.vendors),
                len(written),
                score(found, expected(world)),
                notes,
            )  # fmt: skip
        )
    return Evaluation(scenarios, described)


def write_truth(world_expected: list[Expected], path: Path) -> None:
    path.write_text(
        json.dumps([e.to_dict() for e in world_expected], indent=2) + "\n", encoding="utf-8"
    )


# --- report -----------------------------------------------------------------------------------


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def to_json(ev: Evaluation) -> dict:
    def summary(s: Score) -> dict:
        return {
            "true_positives": s.tp,
            "false_positives": s.fp,
            "false_negatives": s.fn,
            "precision": round(s.precision, 4),
            "recall": round(s.recall, 4),
            "wrong_amounts": len(s.wrong_amounts),
            "dollars_at_stake": str(s.at_stake),
            "dollars_recovered": str(s.recovered),
            "dollars_wrongly_claimed": str(s.wrongly_claimed),
        }

    total = ev.total
    return {
        "extractor": ev.extractor,
        "total": summary(total),
        "by_class": {
            c: {"tp": tp, "fp": fp, "fn": fn} for c, (tp, fp, fn) in total.by_class().items()
        },
        "scenarios": [
            {
                "seed": s.seed,
                "company": s.company,
                "vendors": s.vendors,
                "documents": s.documents,
                **summary(s.score),
                "missed": [e.to_dict() for e in s.score.missed],
                "spurious": [f.to_dict() for f in s.score.spurious],
                "wrong_amounts": [
                    {"expected": e.to_dict(), "found": f.to_dict()}
                    for e, f in s.score.wrong_amounts
                ],
                "notes": s.notes,
            }
            for s in ev.scenarios
        ],
    }


def to_markdown(ev: Evaluation) -> str:
    t = ev.total
    out = [
        "# Ledgerlens evaluation",
        "",
        f"{len(ev.scenarios)} synthetic mailbox(es), read by the {ev.extractor}.",
        "",
        "| Precision | Recall | Found | Missed | False | Wrong amount "
        "| At stake | Recovered | Wrongly claimed |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| {_pct(t.precision)} | {_pct(t.recall)} | {t.tp} | {t.fn} | {t.fp} "
        f"| {len(t.wrong_amounts)} | ${t.at_stake:,.2f} | ${t.recovered:,.2f} "
        f"| ${t.wrongly_claimed:,.2f} |",
        "",
        "## By class",
        "",
        "| Class | Found | Missed | False | Precision | Recall |",
        "|---|---|---|---|---|---|",
    ]
    for c, (tp, fp, fn) in t.by_class().items():
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        out.append(f"| `{c}` | {tp} | {fn} | {fp} | {_pct(p)} | {_pct(r)} |")
    out += [
        "",
        "## By seed",
        "",
        "| Seed | Company | Vendors | Emails | Precision | Recall | Wrongly claimed |",
        "|---|---|---|---|---|---|---|",
    ]
    out += [
        f"| {s.seed} | {s.company} | {s.vendors} | {s.documents} | {_pct(s.score.precision)} "
        f"| {_pct(s.score.recall)} | ${s.score.wrongly_claimed:,.2f} |"
        for s in ev.scenarios
    ]
    errors = [
        s for s in ev.scenarios if s.score.missed or s.score.spurious or s.score.wrong_amounts
    ]
    if errors:
        out += ["", "## Disagreements", ""]
    for s in errors:
        out += [f"### Seed {s.seed}", ""]
        out += [
            f"- missed `{e.cls}` {e.vendor} {e.invoice_id or e.ref}: ${e.amount} ({e.why})"
            for e in s.score.missed
        ]
        out += [
            f"- false `{f.cls}` {f.vendor} {f.invoice_id or ''}: ${f.amount} ({f.summary})"
            for f in s.score.spurious
        ]
        out += [
            f"- `{e.cls}` {e.vendor} {e.invoice_id or e.ref}: expected ${e.amount}, "
            f"found ${f.amount}"
            for e, f in s.score.wrong_amounts
        ]
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def write(ev: Evaluation, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j, m = out_dir / "eval.json", out_dir / "eval.md"
    j.write_text(json.dumps(to_json(ev), indent=2) + "\n", encoding="utf-8")
    m.write_text(to_markdown(ev), encoding="utf-8")
    return j, m
