"""A reviewer answers findings after one batch; the answers shape the next batch's results."""

import shutil
from datetime import UTC, datetime
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest

from ledgerlens import app
from ledgerlens.cli import main
from ledgerlens.decide.feedback import FeedbackError
from ledgerlens.decide.policy import Mode
from ledgerlens.domain.models import Answer, Scope
from ledgerlens.rules.authority import Authority

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"
AUTHORITY = Authority.load(SAMPLES / "authority.toml")


def invoice_email(folder: Path, name: str, sent: str, vendor: str, inv: str, rows: list[str]):
    """Write an .eml carrying a CSV invoice, in the sample mailbox's format."""
    total = sum(Decimal(r.split(",")[-1]) for r in rows)
    csv = "\n".join(
        [
            f"invoice_id,{inv}",
            f"vendor,{vendor}",
            f"issued,{sent}",
            f"due,{sent}",
            f"total,{total}",
            "line,sku,description,period_start,period_end,qty,unit_price,amount",
            *[f"line,{r}" for r in rows],
        ]
    )
    msg = EmailMessage()
    msg["From"] = "Billing <billing@vendor.test>"
    msg["To"] = "AP Team <ap@acme-robotics.com>"
    msg["Subject"] = f"Invoice {inv}"
    msg["Date"] = format_datetime(datetime.fromisoformat(sent).replace(hour=8, tzinfo=UTC))
    msg.set_content("Invoice attached.")
    msg.add_attachment(csv + "\n", subtype="csv", filename=f"{inv}.csv")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.eml").write_bytes(msg.as_bytes())


def mailbox(tmp_path: Path, *batches: str) -> Path:
    box = tmp_path / "box"
    for b in batches:
        shutil.copytree(SAMPLES / b, box / b)
    return box


def by_invoice(result, invoice_id):
    return next(f for f in [*result.findings, *result.closed] if f.invoice_id == invoice_id)


def test_standing_dismissal_closes_later_findings_up_to_its_limit(tmp_path):
    box, state = mailbox(tmp_path, "batch_01"), tmp_path / "state"
    (first,) = run_batches(box, state)
    price = by_invoice(first, "INV-CK-301")
    seats = next(f for f in first.findings if str(f.cls) == "seats_over_licensed")
    app.answer(state, price.id, Answer.DISMISS, Scope.STANDING, "Priya Raman")
    app.answer(state, seats.id, Answer.DISMISS, Scope.ONCE, "Priya Raman")

    nxt = box / "batch_02"
    store = "CK-STORE-TB,Backup storage,{0}-01,{0}-30,40,{1},{2}"
    invoice_email(nxt, "1", "2026-03-02", "Cloudkeep Ltd.", "INV-CK-350",
                  [store.format("2026-03", "23.00", "920.00")])  # fmt: skip
    invoice_email(nxt, "2", "2026-03-03", "Cloudkeep Ltd.", "INV-CK-351",
                  [store.format("2026-04", "25.00", "1000.00")])  # fmt: skip
    invoice_email(nxt, "3", "2026-03-04", "Brightdesk Inc.", "INV-BD-1150",
                  ["BD-PRO,Pro seat,2026-03-01,2026-03-31,132,38.00,5016.00"])  # fmt: skip
    (second,) = run_batches(box, state)

    same = by_invoice(second, "INV-CK-350")
    why = same.details["dismissed_by"]
    assert same in second.closed and "standing dismiss by Priya Raman" in why and price.id in why
    bigger = by_invoice(second, "INV-CK-351")
    assert bigger in second.findings and bigger.amount == Decimal("140.00")
    assert any("covers up to $60.00" in n and bigger.id in n for n in second.notes)
    again = by_invoice(second, "INV-BD-1150")
    assert again in second.findings and str(again.cls) == "seats_over_licensed"


def test_standing_approval_lets_a_large_dispute_through_in_autonomous_mode(tmp_path):
    box, state = mailbox(tmp_path, "batch_01"), tmp_path / "state"
    (first,) = run_batches(box, state, Mode.AUTONOMOUS, Decimal("100"))
    seats = next(f for f in first.findings if str(f.cls) == "seats_over_licensed")
    assert seats.action == "human_review" and not seats.executed
    app.answer(state, seats.id, Answer.APPROVE, Scope.STANDING, "Priya Raman")
    invoice_email(box / "batch_02", "1", "2026-03-04", "Brightdesk Inc.", "INV-BD-1150",
                  ["BD-PRO,Pro seat,2026-03-01,2026-03-31,132,38.00,5016.00"])  # fmt: skip
    (second,) = run_batches(box, state, Mode.AUTONOMOUS, Decimal("100"))
    later = by_invoice(second, "INV-BD-1150")
    assert later.action == "dispute" and later.executed
    assert later.details["approved_by"].startswith("standing approve by Priya Raman")


def test_price_ruling_on_a_conflict_prices_the_next_invoice(tmp_path):
    box, state = mailbox(tmp_path, "batch_01", "batch_02", "batch_03"), tmp_path / "state"
    third = run_batches(box, state)[-1]
    conflict = by_invoice(third, "INV-CK-402")
    assert str(conflict.cls) == "conflict"
    with pytest.raises(FeedbackError):
        app.answer(state, conflict.id, Answer.PRICE, Scope.STANDING, "Priya", price=Decimal(20))
    app.answer(state, conflict.id, Answer.PRICE, Scope.STANDING, "Priya Raman",
               price=Decimal("19.50"), note="email deal stands")  # fmt: skip
    invoice_email(box / "batch_04", "1", "2026-11-02", "Cloudkeep Ltd.", "INV-CK-420",
                  ["CK-STORE-TB,Backup storage,2026-11-01,2026-11-30,40,21.50,860.00"])  # fmt: skip
    (fourth,) = run_batches(box, state)
    (f,) = [f for f in fourth.findings if f.invoice_id == "INV-CK-420"]
    assert (str(f.cls), f.rule, f.amount) == (
        "price_over_contract",
        "unit_price_above_ruled",
        Decimal("80.00"),
    )
    assert "(email deal stands)" in f.evidence[-1].quote


def test_unknown_finding_id_is_refused(tmp_path):
    with pytest.raises(KeyError):
        app.answer(tmp_path, "deadbeef", Answer.DISMISS, Scope.ONCE, "Priya Raman")


def test_cli_review_round_trip_and_reset_keeps_decisions(tmp_path, capsys):
    box, state, out = mailbox(tmp_path, "batch_01"), tmp_path / "s", tmp_path / "o"
    audit = ["audit", str(box), "--state", str(state), "--out", str(out)]
    assert main(audit) == 0
    printed = capsys.readouterr().out
    cancel = next(line for line in printed.splitlines() if "billed_after_cancel" in line)
    fid = cancel.split("]")[1].split()[0]
    assert f"Finding `{fid}`" in (out / "report.md").read_text(encoding="utf-8")

    assert main(["review", fid, "dismiss", "--by", "Priya Raman", "--state", str(state)]) == 0
    assert "dismiss for this finding only" in capsys.readouterr().out
    assert main(["decisions", "--state", str(state)]) == 0
    assert f"{fid}  once" in capsys.readouterr().out

    assert main([*audit, "--reset"]) == 0  # audited again from scratch: the one-off still applies
    assert "3 new finding(s), 1 closed by decisions" in capsys.readouterr().out
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Closed by a reviewer's decision:" in md and f"- `{fid}` `billed_after_cancel`" in md

    assert main(["review", fid, "--revoke", "--state", str(state)]) == 0
    assert main([*audit, "--reset"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "batch_01 (as of 2026-02-10): 4 new finding(s)" in lines


def test_cli_review_errors_are_clear(tmp_path, capsys):
    state = tmp_path / "s"
    for args, msg in [
        (["review", "deadbeef", "dismiss", "--by", "P"], "no finding deadbeef"),
        (["review", "deadbeef", "dismiss"], "--by is required"),
        (["review", "deadbeef"], "give an answer"),
        (["review", "deadbeef", "--revoke"], "no active decision"),
    ]:
        with pytest.raises(SystemExit):
            main([*args, "--state", str(state)])
        assert msg in capsys.readouterr().err


def run_batches(box, state, mode=Mode.SUPERVISED, threshold=Decimal("2500.00")):
    return app.run(box, state, mode, threshold, authority=AUTHORITY)
