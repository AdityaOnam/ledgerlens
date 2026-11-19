"""ledgerlens audit <mailbox> [--mode supervised|autonomous] [--extractor auto|layout|llm]
[--ocr auto|off] [--authority FILE]

With --extractor auto (the default) documents the layout reader cannot parse are sent to Claude
when ANTHROPIC_API_KEY is set and the optional `anthropic` package is installed; otherwise the
layout reader works alone. With --ocr auto (the default) scanned PDFs and images are read by
Tesseract when it is installed; otherwise they are skipped with a note. Who may agree terms is
read from --authority, or from authority.toml at the top of the mailbox; without either, no
authority check is made.

ledgerlens review <finding-id> dismiss|approve|price --by NAME [--standing] [--price P]
[--up-to AMOUNT] [--note TEXT]        (or: ledgerlens review <finding-id> --revoke)
ledgerlens decisions

A reviewer's answer is stored in the state directory and applied from the next audit on: once
to that finding only, or standing to later findings of the same kind as well.

ledgerlens synth <folder> [--seed N] [--vendors K] [--months M] [--batches B]
ledgerlens eval [--seeds 1-20] [--vendors K] [--months M] [--batches B] [--extractor ...]
[--min-precision P] [--min-recall R]

synth writes an invented mailbox with problems planted at random, and TRUTH.json, the findings
an audit of it must produce. eval audits one such mailbox per seed and reports precision, recall
and dollars recovered vs. wrongly claimed; it exits 1 if a --min-* bar is not met."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from ledgerlens import app
from ledgerlens.app import run
from ledgerlens.decide.feedback import FeedbackError
from ledgerlens.decide.policy import DEFAULT_REVIEW_THRESHOLD, Mode
from ledgerlens.domain.dates import parse_date
from ledgerlens.domain.models import Answer, Scope
from ledgerlens.ingest.convert import OCR, default_ocr
from ledgerlens.ingest.extract import Extractor, extract
from ledgerlens.report.render import write
from ledgerlens.rules.authority import Authority, AuthorityError, find
from ledgerlens.store import decisions as decision_log

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


def choose_authority(mailbox: Path, path: Path | None) -> tuple[Authority | None, str]:
    """The authority list for a run, with a one-line description for the console.

    Raises AuthorityError if the file is malformed and FileNotFoundError if an explicit
    --authority file does not exist."""
    path = path or find(mailbox)
    if path is None:
        return None, "not checked (no authority.toml)"
    authority = Authority.load(path)
    return authority, f"{len(authority.signatories)} signatory(ies) from {path}"


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
    a.add_argument(
        "--reset", action="store_true", help="forget all earlier batches (decisions are kept)"
    )
    a.add_argument("--extractor", choices=EXTRACTORS, default="auto")
    a.add_argument("--model", default=None, help="Claude model for --extractor llm/auto")
    a.add_argument("--cache", type=Path, default=Path(".cache/llm"), help="model response cache")
    a.add_argument("--ocr", choices=OCR_CHOICES, default="auto", help="read scans with Tesseract")
    a.add_argument(
        "--authority", type=Path, default=None, help="who may agree terms (TOML; see README)"
    )

    r = sub.add_parser("review", help="answer a reported finding")
    r.add_argument("finding_id", help="the 8-character id shown in the report")
    r.add_argument("answer", nargs="?", choices=[x.value for x in Answer])
    r.add_argument("--by", default="", help="who decided (kept with the decision)")
    r.add_argument(
        "--standing", action="store_true", help="also apply to later findings of the same kind"
    )
    r.add_argument("--price", type=Decimal, default=None, help="the price that settles a conflict")
    r.add_argument("--up-to", type=Decimal, default=None, help="standing: most it may cover")
    r.add_argument("--note", default="")
    r.add_argument("--on", type=parse_date, default=None, help="date of the decision")
    r.add_argument("--revoke", action="store_true", help="withdraw the decisions on this finding")
    r.add_argument("--state", type=Path, default=Path(".state"))

    d = sub.add_parser("decisions", help="list reviewers' decisions")
    d.add_argument("--state", type=Path, default=Path(".state"))

    s = sub.add_parser("synth", help="write a synthetic mailbox and the findings it must produce")
    s.add_argument("folder", type=Path, help="an empty or new folder")
    s.add_argument("--seed", type=int, default=1)
    _world_args(s)

    e = sub.add_parser("eval", help="audit synthetic mailboxes and score them against the oracle")
    e.add_argument("--seeds", default="1-10", help="e.g. 7, 1-20 or 1,4,9-12")
    _world_args(e)
    e.add_argument("--extractor", choices=EXTRACTORS, default="layout")
    e.add_argument("--model", default=None, help="Claude model for --extractor llm/auto")
    e.add_argument("--cache", type=Path, default=Path(".cache/llm"), help="model response cache")
    e.add_argument("--out", type=Path, default=Path("out/eval"))
    e.add_argument("--work", type=Path, default=None, help="keep the mailboxes here (empty dir)")
    e.add_argument("--min-precision", type=float, default=None)
    e.add_argument("--min-recall", type=float, default=None)
    args = p.parse_args(argv)

    if args.cmd == "review":
        return review(p, args)
    if args.cmd == "decisions":
        return list_decisions(args.state)
    if args.cmd == "synth":
        return synth(p, args)
    if args.cmd == "eval":
        return evaluate(p, args)
    return audit(p, args)


def _world_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--vendors", type=int, default=6, help="vendors per mailbox (1-12)")
    sp.add_argument("--months", type=int, default=6, help="months of invoices")
    sp.add_argument("--batches", type=int, default=2, help="batches the months are split into")


def _empty_dir(p: argparse.ArgumentParser, folder: Path) -> None:
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        p.error(f"{folder} is not empty; choose a new or empty folder")


def synth(p: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from ledgerlens.evaluate.oracle import expected
    from ledgerlens.evaluate.runner import write_truth
    from ledgerlens.evaluate.synth import generate, write_mailbox

    _empty_dir(p, args.folder)
    try:
        world = generate(args.seed, args.vendors, args.months, args.batches)
    except ValueError as exc:
        p.error(str(exc))
    written = write_mailbox(world, args.folder)
    truth = expected(world)
    write_truth(truth, args.folder / "TRUTH.json")
    print(
        f"{world.company}: {len(world.vendors)} vendors, {len(written)} emails in "
        f"{len(world.cutoffs)} batch(es); {len(truth)} expected finding(s) in "
        f"{args.folder / 'TRUTH.json'}"
    )
    return 0


def evaluate(p: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from ledgerlens.evaluate import runner

    try:
        seeds = runner.parse_seeds(args.seeds)
    except ValueError as exc:
        p.error(f"--seeds: {exc}")
    extractor, described = choose_extractor(args.extractor, args.cache, args.model)
    if args.work is not None:
        _empty_dir(p, args.work)
    with tempfile.TemporaryDirectory(prefix="ledgerlens-eval-") as tmp:
        try:
            ev = runner.evaluate(
                seeds,
                args.work or Path(tmp),
                args.vendors,
                args.months,
                args.batches,
                extractor=extractor,
                described=described,
            )
        except ValueError as exc:
            p.error(str(exc))
    t = ev.total
    print(f"Extractor: {described}; {len(seeds)} mailbox(es)")
    print(
        f"Precision {t.precision:.1%}  recall {t.recall:.1%}  "
        f"({t.tp} found, {t.fn} missed, {t.fp} false, {len(t.wrong_amounts)} wrong amount)"
    )
    print(
        f"Dollars: ${t.at_stake:,.2f} at stake, ${t.recovered:,.2f} recovered, "
        f"${t.wrongly_claimed:,.2f} wrongly claimed"
    )
    _, md_path = runner.write(ev, args.out)
    print(f"Report: {md_path}")
    failed = []
    if args.min_precision is not None and t.precision < args.min_precision:
        failed.append(f"precision {t.precision:.4f} < {args.min_precision}")
    if args.min_recall is not None and t.recall < args.min_recall:
        failed.append(f"recall {t.recall:.4f} < {args.min_recall}")
    for msg in failed:
        print(f"FAILED: {msg}", file=sys.stderr)
    return 1 if failed else 0


def review(p: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        if args.revoke:
            if args.answer:
                p.error("--revoke takes no answer")
            app.revoke(args.state, args.finding_id, args.on)
            print(f"Withdrew the decisions on finding {args.finding_id}.")
            return 0
        if not args.answer:
            p.error("give an answer (dismiss, approve or price) or --revoke")
        if not args.by:
            p.error("--by is required: say who decided")
        dec = app.answer(
            args.state,
            args.finding_id,
            Answer(args.answer),
            Scope.STANDING if args.standing else Scope.ONCE,
            args.by,
            args.on,
            price=args.price,
            up_to=args.up_to,
            note=args.note,
        )
    except KeyError:
        p.error(f"no finding {args.finding_id} in {args.state} (ids are in the report)")
    except FeedbackError as exc:
        p.error(str(exc))
    reach = "this finding only"
    if dec.standing:
        reach = f"this and later {dec.cls} findings for {dec.vendor}"
        reach += f" / {dec.sku}" if dec.sku else ""
        reach += f" up to ${dec.up_to}" if dec.up_to is not None else ""
    what = f"${dec.price} governs" if dec.price is not None else str(dec.answer)
    print(f"Recorded: {what} for {reach}. Applies from the next audit.")
    return 0


def list_decisions(state: Path) -> int:
    decisions = decision_log.load(state / decision_log.FILENAME)
    if not decisions:
        print("No decisions recorded.")
        return 0
    for dec in decisions:
        status = "active" if dec.active else f"revoked {dec.revoked_on}"
        what = f"price ${dec.price}" if dec.price is not None else str(dec.answer)
        limit = f" up to ${dec.up_to}" if dec.up_to is not None else ""
        print(
            f"{dec.finding_id}  {dec.scope:<8} {what:<14} {dec.cls:<20} {dec.vendor:<16}"
            f"{limit}  {dec.reviewer}, {dec.decided_on}  [{status}]"
        )
    return 0


def audit(p: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if not args.mailbox.is_dir():
        p.error(f"mailbox not found: {args.mailbox}")
    if args.reset:
        (args.state / app.MEMORY_FILE).unlink(missing_ok=True)
    extractor, described = choose_extractor(args.extractor, args.cache, args.model)
    ocr, ocr_described = choose_ocr(args.ocr)
    try:
        authority, auth_described = choose_authority(args.mailbox, args.authority)
    except (OSError, AuthorityError) as exc:
        p.error(f"authority file: {exc}")
    print(f"Extractor: {described}; OCR: {ocr_described}")
    print(f"Authority: {auth_described}")
    results = run(
        args.mailbox,
        args.state,
        Mode(args.mode),
        args.threshold,
        args.as_of,
        extractor=extractor,
        ocr=ocr,
        authority=authority,
    )
    if not results:
        print("No new batches.")
        return 0
    for r in results:
        closed = f", {len(r.closed)} closed by decisions" if r.closed else ""
        print(f"{r.batch} (as of {r.as_of}): {len(r.findings)} new finding(s){closed}")
        for f in r.findings:
            flag = "x" if f.executed else " "
            print(f"  [{flag}] {f.id}  {f.cls:<20} {f.vendor:<16} ${f.amount:>10,.2f}  {f.action}")
    json_path, md_path = write(results, args.out)
    print(f"Report: {md_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
