"""docs/demo is what scripts/make_demo.py writes from the sample mailbox."""

import json
from pathlib import Path

import pytest

from ledgerlens.app import run
from ledgerlens.decide.policy import Mode
from ledgerlens.ingest.extract import extract
from ledgerlens.report.render import to_json, to_markdown
from ledgerlens.rules.authority import Authority

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples" / "acme"
DEMO = ROOT / "docs" / "demo"


@pytest.mark.parametrize("mode", list(Mode), ids=lambda m: m.value)
def test_demo_reports_are_up_to_date(tmp_path, mode):
    authority = Authority.load(SAMPLES / "authority.toml")
    results = run(SAMPLES, tmp_path, mode, extractor=extract, authority=authority)
    folder = DEMO / mode.value
    hint = "run: python scripts/make_demo.py"
    md = (folder / "report.md").read_text(encoding="utf-8")
    assert md == to_markdown(results), hint
    assert json.loads((folder / "report.json").read_text(encoding="utf-8")) == to_json(results)


def test_only_autonomous_mode_executes_anything():
    def executed(mode: Mode) -> int:
        data = json.loads((DEMO / mode.value / "report.json").read_text(encoding="utf-8"))
        return sum(f["executed"] for b in data["batches"] for f in b["findings"])

    assert executed(Mode.SUPERVISED) == 0
    assert executed(Mode.AUTONOMOUS) > 0
