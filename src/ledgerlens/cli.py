"""ledgerlens audit <mailbox> [--mode supervised|autonomous] [--extractor auto|layout|llm]
[--ocr auto|off]

With --extractor auto (the default) documents the layout reader cannot parse are sent to Claude
when ANTHROPIC_API_KEY is set and the optional `anthropic` package is installed; otherwise the
layout reader works alone. With --ocr auto (the default) scanned PDFs and images are read by
Tesseract when it is installed; otherwise they are skipped with a note."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from ledgerlens.app import run
from ledgerlens.decide.policy import DEFAULT_REVIEW_THRESHOLD, Mode
from ledgerlens.domain.dates import parse_date
from ledgerlens.ingest.convert import OCR, default_ocr
from ledgerlens.ingest.extract import Extractor, extract
from ledgerlens.report.render import write

EXTRACTORS = ("auto", "layout", "llm")
OCR_CHOICES = ("auto", "off")


def choose_ocr(name: str) -> tuple[OCR | None, str]:
    """The OCR engine for scanned attachments, with a one-line description for the console."""
    if name == "off":
        return None, "off"
    engine = default_ocr()
    if engine is None:
        return None, 'unavailable (install Tesseract and "ledgerlens[ocr]")'
    return engine, "Tesseract"


def choose_extractor(
    name: str, cache_dir: Path, model: str | None = None, env: Mapping[str, str] | None = None
) -> tuple[Extractor, str]:
    """Pick the extractor; returns it with a one-line description for the console.

    Raises SystemExit with a clear message if 'llm' is asked for but cannot run."""
    env = os.environ if env is None else env
    has_key = bool(env.get("ANTHROPIC_API_KEY"))
    has_sdk = importlib.util.find_spec("anthropic") is not None
    if name == "layout" or (name == "auto" and not (has_key and has_sdk)):
        why = ""
        if name == "auto":
            why = " (ANTHROPIC_API_KEY not set)" if not has_key else " (anthropic not installed)"
        return extract, f"layout reader{why}"
    if not has_key:
        raise SystemExit("--extractor llm needs ANTHROPIC_API_KEY in the environment")
    if not has_sdk:
        raise SystemExit('--extractor llm needs the SDK: pip install "ledgerlens[llm]"')
    from ledgerlens.ingest.llm import DEFAULT_MODEL, AnthropicClient, LLMExtractor

    client = AnthropicClient(model or DEFAULT_MODEL)
    return LLMExtractor(client, cache_dir), f"layout reader + {client.model} (cache: {cache_dir})"


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
    a.add_argument("--extractor", choices=EXTRACTORS, default="auto")
    a.add_argument("--model", default=None, help="Claude model for --extractor llm/auto")
    a.add_argument("--cache", type=Path, default=Path(".cache/llm"), help="model response cache")
    a.add_argument("--ocr", choices=OCR_CHOICES, default="auto", help="read scans with Tesseract")
    args = p.parse_args(argv)

    if not args.mailbox.is_dir():
        p.error(f"mailbox not found: {args.mailbox}")
    if args.reset and args.state.exists():
        shutil.rmtree(args.state)
    extractor, described = choose_extractor(args.extractor, args.cache, args.model)
    ocr, ocr_described = choose_ocr(args.ocr)
    print(f"Extractor: {described}; OCR: {ocr_described}")
    results = run(
        args.mailbox,
        args.state,
        Mode(args.mode),
        args.threshold,
        args.as_of,
        extractor=extractor,
        ocr=ocr,
    )
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
