"""ledgerlens audit <mailbox> [--mode supervised|autonomous] [--state DIR] [--out DIR]"""

from __future__ import annotations

import argparse
import shutil
import sys
from decimal import Decimal
from pathlib import Path

from ledgerlens.app import run
from ledgerlens.decide.policy import DEFAULT_REVIEW_THRESHOLD, Mode
from ledgerlens.domain.dates import parse_date
from ledgerlens.report.render import write


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ledgerlens", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="process new batches in a mailbox")
    a.add_argument("mailbox", type=Path)
    a.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.SUPERVISED.value)
    a.add_argument("--state", type=Path, default=Path(".state"))
    a.add_argument("--out", type=Path, default=Path("out"))
    a.add_argument("--threshold", type=Decimal, default=DEFAULT_REVIEW_THRESHOLD)
    a.add_argument("--as-of", type=parse_date, default=None)
    a.add_argument("--reset", action="store_true", help="forget all earlier batches first")
    args = p.parse_args(argv)

    if not args.mailbox.is_dir():
        p.error(f"mailbox not found: {args.mailbox}")
    if args.reset and args.state.exists():
        shutil.rmtree(args.state)
    results = run(args.mailbox, args.state, Mode(args.mode), args.threshold, args.as_of)
    if not results:
        print("No new batches.")
        return 0
    for r in results:
        print(f"{r.batch} (as of {r.as_of}): {len(r.findings)} new finding(s)")
        for f in r.findings:
            flag = "x" if f.executed else " "
            print(f"  [{flag}] {f.cls:<20} {f.vendor:<16} ${f.amount:>10,.2f}  {f.action}")
    json_path, md_path = write(results, args.out)
    print(f"Report: {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
