"""The sample mailbox must produce exactly the findings in data/samples/acme/EXPECTED.md."""

from pathlib import Path

from ledgerlens.app import run
from ledgerlens.cli import main
from ledgerlens.decide.policy import Mode
from ledgerlens.rules.authority import Authority

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"
AUTHORITY = Authority.load(SAMPLES / "authority.toml")

EXPECTED = {
    "batch_01": {
        ("price_over_contract", "INV-CK-301", "60.00"),
        ("seats_over_licensed", "INV-BD-1078", "456.00"),
        ("billed_after_cancel", "INV-BD-1078", "600.00"),
        ("renewal_notice_due", None, "7200.00"),
    },
    "batch_02": {
        ("duplicate_charge", "INV-CK-301A", "860.00"),
        ("uplift_over_cap", "INV-PW-077", "30.00"),
        ("conflict", "INV-BD-1190", "360.00"),
        ("cannot_determine", "INV-FX-0009", "2400.00"),
        ("credit_not_applied", None, "350.00"),
        ("renewal_notice_due", None, "54720.00"),
    },
    "batch_03": {
        ("conflict", "INV-CK-402", "80.00"),
        ("cannot_determine", "INV-PW-120", "150.00"),
        ("cannot_determine", "INV-TH-233", "90.00"),
    },
}


def findings(results):
    return {
        r.batch: {(str(f.cls), f.invoice_id, str(f.amount)) for f in r.findings} for r in results
    }


def test_sample_mailbox_matches_expected(tmp_path):
    assert findings(run(SAMPLES, tmp_path, Mode.SUPERVISED, authority=AUTHORITY)) == EXPECTED


def test_without_the_authority_file_the_unauthorised_amendment_binds(tmp_path):
    got = findings(run(SAMPLES, tmp_path, Mode.SUPERVISED))
    assert got["batch_03"] == EXPECTED["batch_03"] - {("cannot_determine", "INV-PW-120", "150.00")}
    assert {k: v for k, v in got.items() if k != "batch_03"} == {
        k: v for k, v in EXPECTED.items() if k != "batch_03"
    }


def test_authority_finding_asks_a_signatory_for_sign_off(tmp_path):
    results = run(SAMPLES, tmp_path, authority=AUTHORITY)
    f = next(f for f in results[-1].findings if f.rule == "term_agreed_without_authority")
    assert f.details["holder"] == "priya.raman@acme-robotics.com"
    assert f.details["agreed_by"] == "Dev Malhotra, Engineering Manager"


def test_every_finding_cites_evidence(tmp_path):
    for r in run(SAMPLES, tmp_path, Mode.AUTONOMOUS, authority=AUTHORITY):
        for f in r.findings:
            assert f.evidence and all(e.quote and e.doc_id for e in f.evidence)


def test_rerun_reports_nothing_new(tmp_path):
    run(SAMPLES, tmp_path, authority=AUTHORITY)
    assert run(SAMPLES, tmp_path, authority=AUTHORITY) == []


def test_cannot_determine_names_the_missing_document_and_holder(tmp_path):
    findings = [f for r in run(SAMPLES, tmp_path) for f in r.findings]
    cd = next(f for f in findings if str(f.cls) == "cannot_determine")
    assert cd.details["missing"] == "OF-2026-052" and cd.details["holder"] == "ar@fluxmetrics.io"


def test_cli_writes_reports(tmp_path, capsys):
    code = main(
        ["audit", str(SAMPLES), "--state", str(tmp_path / "s"), "--out", str(tmp_path / "o")]
    )
    assert code == 0
    md = (tmp_path / "o" / "report.md").read_text(encoding="utf-8")
    assert "**13 findings, $2,356.00 recoverable.**" in md
