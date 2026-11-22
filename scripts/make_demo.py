"""Write the demo reports in docs/demo from the sample mailbox.

The Acme Robotics mailbox (invented) is audited from scratch, with its authority.toml, once in
each mode. The reports are committed so they can be read without installing anything; CI runs
this script and fails if they are out of date.

    python scripts/make_demo.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ledgerlens.app import run  # noqa: E402
from ledgerlens.decide.policy import Mode  # noqa: E402
from ledgerlens.ingest.extract import extract  # noqa: E402
from ledgerlens.report.render import to_json, to_markdown  # noqa: E402
from ledgerlens.rules.authority import Authority  # noqa: E402

SAMPLES = ROOT / "data" / "samples" / "acme"
OUT = ROOT / "docs" / "demo"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # LF on every platform, so CI can diff it


def main() -> None:
    authority = Authority.load(SAMPLES / "authority.toml")
    for mode in Mode:
        with tempfile.TemporaryDirectory() as state:
            # The layout reader only: the demo must not depend on a model or a cache.
            results = run(SAMPLES, Path(state), mode, extractor=extract, authority=authority)
        folder = OUT / mode.value
        _write(folder / "report.md", to_markdown(results))
        _write(folder / "report.json", json.dumps(to_json(results), indent=2) + "\n")
        found = sum(len(r.findings) for r in results)
        print(f"{mode.value}: {found} findings -> {folder.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
