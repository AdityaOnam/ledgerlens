"""JSON for machines, Markdown for the AP team."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from ledgerlens.app import BatchResult
from ledgerlens.domain.models import FindingClass

RECOVERABLE = {
    FindingClass.PRICE_OVER_CONTRACT,
    FindingClass.SEATS_OVER_LICENSED,
    FindingClass.UPLIFT_OVER_CAP,
    FindingClass.BILLED_AFTER_CANCEL,
    FindingClass.DUPLICATE_CHARGE,
    FindingClass.CREDIT_NOT_APPLIED,
}


def to_json(results: list[BatchResult]) -> dict:
    return {
        "batches": [
            {
                "batch": r.batch,
                "as_of": r.as_of.isoformat(),
                "notes": r.notes,
                "findings": [f.to_dict() for f in r.findings],
                "closed": [f.to_dict() for f in r.closed],
            }
            for r in results
        ]
    }


def to_markdown(results: list[BatchResult]) -> str:
    all_findings = [f for r in results for f in r.findings]
    recoverable = sum((f.amount for f in all_findings if f.cls in RECOVERABLE), Decimal(0))
    counts = Counter(str(f.cls) for f in all_findings)
    out = [
        "# Ledgerlens audit report",
        "",
        f"**{len(all_findings)} findings, ${recoverable:,.2f} recoverable.**",
        "",
        "| Class | Count |",
        "|---|---|",
    ]
    out += [f"| `{k}` | {v} |" for k, v in sorted(counts.items())]
    for r in results:
        out += ["", f"## {r.batch} (as of {r.as_of})", ""]
        if not r.findings and not r.closed:
            out.append("No new findings.")
        for f in r.findings:
            state = "done" if f.executed else "recommended"
            where = " / ".join(x for x in (f.invoice_id, f.sku) if x)
            out += [
                f"### `{f.cls}`: {f.vendor}{' / ' + where if where else ''}, ${f.amount:,.2f}",
                "",
                f.summary,
                "",
                f"Action: **{f.action}** ({state}). Rule: `{f.rule}`. Finding `{f.id}`.",
                "",
            ]
            if f.details.get("approved_by"):
                out += [f"Approved: {f.details['approved_by']}.", ""]
            for e in f.evidence:
                out += [f"> {e.quote}  ", f"> source: `{e.doc_id}`", ""]
        if r.closed:
            out += ["", "Closed by a reviewer's decision:", ""]
            out += [
                f"- `{f.id}` `{f.cls}` {f.vendor}, ${f.amount:,.2f}: {f.summary}. "
                f"Dismissed: {f.details['dismissed_by']}."
                for f in r.closed
            ]
        if r.notes:
            out += ["", "Notes:", *[f"- {n}" for n in r.notes]]
    return "\n".join(out) + "\n"


def write(results: list[BatchResult], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j, m = out_dir / "report.json", out_dir / "report.md"
    j.write_text(json.dumps(to_json(results), indent=2), encoding="utf-8")
    m.write_text(to_markdown(results), encoding="utf-8")
    return j, m
