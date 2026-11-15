"""Write the sample mailbox for Acme Robotics (invented) to data/samples/acme.

Three batches of .eml files, plus authority.toml (who at Acme may agree terms). Each planted
problem is listed in data/samples/acme/EXPECTED.md, together with the decoys that look wrong
but are fine.

    python scripts/make_samples.py
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"
PRIYA = "Priya Raman <priya.raman@acme-robotics.com>"
DEV = "Dev Malhotra <dev.malhotra@acme-robotics.com>"
AP = "AP Team <ap@acme-robotics.com>"
FINANCE = "Priya Raman, VP Finance"

AUTHORITY = """# Who at Acme Robotics may agree prices and sign contracts with vendors (invented).
[[signatory]]
name = "Priya Raman"
email = "priya.raman@acme-robotics.com"
"""


def order_form(
    ref: str,
    vendor: str,
    contact: str,
    start: str,
    end: str,
    renew: str,
    notice: int,
    cap: str | None,
    true_up: str,
    rows: list[tuple],
) -> str:
    lines = [
        f"ORDER FORM {ref}",
        f"Vendor: {vendor}",
        "Customer: Acme Robotics Ltd.",
        f"Vendor contact: {contact}",
        f"Term start: {start}",
        f"Term end: {end}",
        f"Auto-renewal: {renew}",
        f"Notice period: {notice} days",
    ]
    if cap:
        lines.append(f"Renewal uplift cap: {cap}")
    lines += [
        f"True-up: {true_up}",
        "Signed: Priya Raman, VP Finance",
        "",
        "| SKU | Description | Unit price (USD / month) | Quantity |",
    ]
    lines += [f"| {s} | {d} | {p} | {q} |" for s, d, p, q in rows]
    return "\n".join(lines) + "\n"


def amendment(
    ref: str,
    base: str,
    vendor: str,
    contact: str,
    effective: str,
    end: str,
    rows: list[tuple],
    signed: str = FINANCE,
) -> str:
    lines = [
        f"AMENDMENT {ref} to {base}",
        f"Vendor: {vendor}",
        f"Vendor contact: {contact}",
        f"Effective: {effective}",
        f"Term end: {end}",
        f"Signed: {signed}",
        "",
        "| SKU | Description | Unit price (USD / month) | Quantity |",
    ]
    lines += [f"| {s} | {d} | {p} | {q} |" for s, d, p, q in rows]
    return "\n".join(lines) + "\n"


def invoice(
    inv: str, vendor: str, issued: str, due: str, lines: list[tuple], credits: list[tuple] = ()
) -> str:
    total = sum(float(a) for *_, a in lines) + sum(float(a) for _, a in credits)
    out = [
        f"invoice_id,{inv}",
        f"vendor,{vendor}",
        f"issued,{issued}",
        f"due,{due}",
        f"total,{total:.2f}",
        "line,sku,description,period_start,period_end,qty,unit_price,amount",
    ]
    out += ["line," + ",".join(str(c) for c in row) for row in lines]
    out += [f"credit,{ref},{amt}" for ref, amt in credits]
    return "\n".join(out) + "\n"


def mail(
    batch: str,
    name: str,
    sent: str,
    sender: str,
    to: str,
    subject: str,
    body: str,
    attachments: dict[str, str] | None = None,
) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, subject
    msg["Date"] = format_datetime(datetime.fromisoformat(sent).replace(tzinfo=UTC))
    msg.set_content(body)
    for filename, text in (attachments or {}).items():
        subtype = "csv" if filename.endswith(".csv") else "plain"
        msg.add_attachment(text, subtype=subtype, filename=filename)
    if msg.is_multipart():
        msg.set_boundary(f"==ledgerlens-{name}==")  # fixed, so regenerating is byte-identical
    folder = ROOT / batch
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.eml").write_bytes(msg.as_bytes())


BD = ("Brightdesk Inc.", "accounts@brightdesk.io", "Brightdesk Billing <billing@brightdesk.io>")
CK = ("Cloudkeep Ltd.", "sales@cloudkeep.com", "Cloudkeep Support <support@cloudkeep.com>")
PW = ("Pagewise", "team@pagewise.app", "Pagewise Billing <billing@pagewise.app>")
FX = ("Fluxmetrics", "ar@fluxmetrics.io", "Fluxmetrics AR <ar@fluxmetrics.io>")
TH = ("Tallyhub", "accounts@tallyhub.co", "Tallyhub Billing <billing@tallyhub.co>")


def batch_01() -> None:
    b = "batch_01"
    mail(
        b,
        "001_brightdesk_order_form",
        "2025-11-20T10:00:00",
        BD[2],
        PRIYA,
        "Countersigned order form OF-2025-311",
        "Hi Priya, attached is the countersigned order form.\n",
        {
            "OF-2025-311.txt": order_form(
                "OF-2025-311",
                BD[0],
                BD[1],
                "2025-12-01",
                "2026-11-30",
                "yes",
                60,
                "7%",
                "not permitted",
                [
                    ("BD-PRO", "Brightdesk Pro seat", "38.00", 120),
                    ("BD-ANALYTICS", "Analytics add-on", "600.00", 1),
                ],
            )
        },
    )
    mail(
        b,
        "002_cloudkeep_order_form",
        "2025-12-15T09:30:00",
        CK[2],
        PRIYA,
        "Cloudkeep order form",
        "Please find the signed order form attached.\n",
        {
            "OF-2026-019.txt": order_form(
                "OF-2026-019",
                CK[0],
                CK[1],
                "2026-01-01",
                "2026-12-31",
                "no",
                30,
                None,
                "permitted at contract price",
                [("CK-STORE-TB", "Backup storage, per TB", "21.50", 40)],
            )
        },
    )
    mail(
        b,
        "003_pagewise_order_form",
        "2025-03-20T12:00:00",
        PW[2],
        PRIYA,
        "Pagewise order",
        "Welcome to Pagewise!\n",
        {
            "OF-2025-090.txt": order_form(
                "OF-2025-090",
                PW[0],
                PW[1],
                "2025-04-01",
                "2026-03-31",
                "yes",
                30,
                "5%",
                "not permitted",
                [("PW-TEAM", "Pagewise Team seat", "12.00", 50)],
            )
        },
    )
    mail(
        b,
        "004_brightdesk_jan",
        "2026-01-01T08:00:00",
        BD[2],
        AP,
        "Invoice INV-BD-1041",
        "Your January invoice is attached.\n",
        {
            "INV-BD-1041.csv": invoice(
                "INV-BD-1041",
                BD[0],
                "2026-01-01",
                "2026-01-31",
                [
                    ("BD-PRO", "Pro seat", "2026-01-01", "2026-01-31", 120, "38.00", "4560.00"),
                    (
                        "BD-ANALYTICS",
                        "Analytics add-on",
                        "2026-01-01",
                        "2026-01-31",
                        1,
                        "600.00",
                        "600.00",
                    ),
                ],
            )
        },
    )
    mail(
        b,
        "005_cloudkeep_jan",
        "2026-01-02T08:00:00",
        CK[2],
        AP,
        "Invoice INV-CK-301",
        "Invoice attached.\n",
        {
            "INV-CK-301.csv": invoice(
                "INV-CK-301",
                CK[0],
                "2026-01-02",
                "2026-02-01",
                [
                    (
                        "CK-STORE-TB",
                        "Backup storage",
                        "2026-01-01",
                        "2026-01-31",
                        40,
                        "23.00",
                        "920.00",
                    )
                ],
            )
        },
    )
    mail(
        b,
        "006_cancel_analytics",
        "2026-01-20T15:12:00",
        PRIYA,
        BD[2],
        "Cancel analytics add-on",
        "Hi team,\n\nWe no longer use the dashboards. Please cancel BD-ANALYTICS effective "
        "2026-02-01.\n\nThanks,\nPriya\n",
    )
    mail(
        b,
        "007_cloudkeep_outage",
        "2026-02-10T11:00:00",
        CK[2],
        PRIYA,
        "January outage",
        "Hi Priya,\n\nApologies for the January backup outage. We will apply a service credit of "
        "$350.00 to your next invoice (ref SLA-2026-02).\n\nCloudkeep Support\n",
    )
    mail(
        b,
        "008_brightdesk_feb",
        "2026-02-01T08:00:00",
        BD[2],
        AP,
        "Invoice INV-BD-1078",
        "Your February invoice is attached.\n",
        {
            "INV-BD-1078.csv": invoice(
                "INV-BD-1078",
                BD[0],
                "2026-02-01",
                "2026-03-03",
                [
                    ("BD-PRO", "Pro seat", "2026-02-01", "2026-02-28", 132, "38.00", "5016.00"),
                    (
                        "BD-ANALYTICS",
                        "Analytics add-on",
                        "2026-02-01",
                        "2026-02-28",
                        1,
                        "600.00",
                        "600.00",
                    ),
                ],
            )
        },
    )
    # Decoy: Cloudkeep bills 44 TB, but true-up is permitted at contract price.
    mail(
        b,
        "009_cloudkeep_feb",
        "2026-02-02T08:00:00",
        CK[2],
        AP,
        "Invoice INV-CK-309",
        "Invoice attached.\n",
        {
            "INV-CK-309.csv": invoice(
                "INV-CK-309",
                CK[0],
                "2026-02-02",
                "2026-03-04",
                [
                    (
                        "CK-STORE-TB",
                        "Backup storage",
                        "2026-02-01",
                        "2026-02-28",
                        44,
                        "21.50",
                        "946.00",
                    )
                ],
            )
        },
    )


def batch_02() -> None:
    b = "batch_02"
    mail(
        b,
        "101_brightdesk_mar",
        "2026-03-01T08:00:00",
        BD[2],
        AP,
        "Invoice INV-BD-1102",
        "Your March invoice is attached.\n",
        {
            "INV-BD-1102.csv": invoice(
                "INV-BD-1102",
                BD[0],
                "2026-03-01",
                "2026-03-31",
                [("BD-PRO", "Pro seat", "2026-03-01", "2026-03-31", 120, "38.00", "4560.00")],
            )
        },
    )
    mail(
        b,
        "102_cloudkeep_mar",
        "2026-03-02T08:00:00",
        CK[2],
        AP,
        "Invoice INV-CK-318",
        "Invoice attached.\n",
        {
            "INV-CK-318.csv": invoice(
                "INV-CK-318",
                CK[0],
                "2026-03-02",
                "2026-04-01",
                [
                    (
                        "CK-STORE-TB",
                        "Backup storage",
                        "2026-03-01",
                        "2026-03-31",
                        40,
                        "21.50",
                        "860.00",
                    )
                ],
            )
        },
    )
    mail(
        b,
        "103_cloudkeep_rebill",
        "2026-03-20T08:00:00",
        CK[2],
        AP,
        "Corrected invoice INV-CK-301A",
        "Please find a corrected copy for January.\n",
        {
            "INV-CK-301A.csv": invoice(
                "INV-CK-301A",
                CK[0],
                "2026-03-20",
                "2026-04-19",
                [
                    (
                        "CK-STORE-TB",
                        "Backup storage",
                        "2026-01-01",
                        "2026-01-31",
                        40,
                        "21.50",
                        "860.00",
                    )
                ],
            )
        },
    )
    # Renewal at 10 % uplift; the cap is 5 %.
    mail(
        b,
        "104_pagewise_renewal",
        "2026-04-01T08:00:00",
        PW[2],
        AP,
        "Invoice INV-PW-077",
        "Thanks for renewing!\n",
        {
            "INV-PW-077.csv": invoice(
                "INV-PW-077",
                PW[0],
                "2026-04-01",
                "2026-05-01",
                [("PW-TEAM", "Team seat", "2026-04-01", "2026-04-30", 50, "13.20", "660.00")],
            )
        },
    )
    # Two signed amendments, same day, different Pro price: a conflict for a person.
    mail(
        b,
        "105_brightdesk_amendment",
        "2026-05-25T10:00:00",
        BD[2],
        PRIYA,
        "Amendment AM-2026-03",
        "Signed amendment attached.\n",
        {
            "AM-2026-03.txt": amendment(
                "AM-2026-03",
                "OF-2025-311",
                BD[0],
                BD[1],
                "2026-06-01",
                "2026-11-30",
                [("BD-PRO", "Brightdesk Pro seat", "36.00", 120)],
            )
        },
    )
    mail(
        b,
        "106_brightdesk_amendment_v2",
        "2026-05-27T10:00:00",
        BD[2],
        PRIYA,
        "Amendment AM-2026-04 (reissued)",
        "Reissued amendment attached.\n",
        {
            "AM-2026-04.txt": amendment(
                "AM-2026-04",
                "OF-2025-311",
                BD[0],
                BD[1],
                "2026-06-01",
                "2026-11-30",
                [("BD-PRO", "Brightdesk Pro seat", "35.00", 120)],
            )
        },
    )
    mail(
        b,
        "107_brightdesk_jun",
        "2026-06-01T08:00:00",
        BD[2],
        AP,
        "Invoice INV-BD-1190",
        "Your June invoice is attached.\n",
        {
            "INV-BD-1190.csv": invoice(
                "INV-BD-1190",
                BD[0],
                "2026-06-01",
                "2026-07-01",
                [("BD-PRO", "Pro seat", "2026-06-01", "2026-06-30", 120, "38.00", "4560.00")],
            )
        },
    )
    # Fluxmetrics: no order form on file.
    mail(
        b,
        "108_fluxmetrics_intro",
        "2026-07-03T09:00:00",
        FX[2],
        PRIYA,
        "Welcome aboard",
        "Hi Priya, hosting starts this month per order form OF-2026-052. "
        "Invoices follow monthly.\n",
    )
    mail(
        b,
        "109_fluxmetrics_jul",
        "2026-07-05T08:00:00",
        FX[2],
        AP,
        "Invoice INV-FX-0009",
        "Invoice attached.\n",
        {
            "INV-FX-0009.csv": invoice(
                "INV-FX-0009",
                FX[0],
                "2026-07-05",
                "2026-08-04",
                [
                    (
                        "FX-HOST",
                        "Managed hosting",
                        "2026-07-01",
                        "2026-07-31",
                        1,
                        "2400.00",
                        "2400.00",
                    )
                ],
            )
        },
    )
    mail(
        b,
        "110_ap_status",
        "2026-09-15T09:00:00",
        AP,
        PRIYA,
        "AP status",
        "Monthly AP status: all vendor invoices through September are entered.\n",
    )


def batch_03() -> None:
    """Several sources on one price: precedence, authority and a document never received."""
    b = "batch_03"
    mail(
        b,
        "201_tallyhub_order_form",
        "2026-07-25T10:00:00",
        TH[2],
        PRIYA,
        "Tallyhub order form OF-2026-071",
        "Countersigned copy attached.\n",
        {
            "OF-2026-071.txt": order_form(
                "OF-2026-071",
                TH[0],
                TH[1],
                "2026-08-01",
                "2027-07-31",
                "no",
                30,
                None,
                "not permitted",
                [("TH-SEAT", "Tallyhub seat", "20.00", 30)],
            )
        },
    )
    # Superseded: a signed amendment takes effect after this email and sets its own price.
    mail(
        b,
        "202_tallyhub_price_email",
        "2026-08-20T14:00:00",
        TH[2],
        PRIYA,
        "Seat price",
        "Hi Priya,\n\nAs discussed on our call, the price for TH-SEAT will be $18.00 per seat "
        "effective 2026-09-01.\n\nTallyhub Accounts\n",
    )
    mail(
        b,
        "203_tallyhub_amendment",
        "2026-09-25T10:00:00",
        TH[2],
        PRIYA,
        "Amendment AM-2026-08",
        "Signed amendment attached.\n",
        {
            "AM-2026-08.txt": amendment(
                "AM-2026-08",
                "OF-2026-071",
                TH[0],
                TH[1],
                "2026-10-01",
                "2027-07-31",
                [("TH-SEAT", "Tallyhub seat", "19.00", 30)],
            )
        },
    )
    # A later email disagrees with the signed order form: a conflict for a person.
    mail(
        b,
        "204_cloudkeep_price_email",
        "2026-09-20T11:00:00",
        CK[2],
        PRIYA,
        "Storage pricing",
        "Hi Priya,\n\nFollowing our call, the price for CK-STORE-TB will be $19.50 per TB "
        "effective 2026-10-01.\n\nCloudkeep Sales\n",
    )
    # Signed by someone who may not agree terms.
    mail(
        b,
        "205_pagewise_amendment",
        "2026-09-28T09:00:00",
        PW[2],
        DEV,
        "Amendment AM-2026-06",
        "Signed amendment for the extra seats attached.\n",
        {
            "AM-2026-06.txt": amendment(
                "AM-2026-06",
                "OF-2025-090",
                PW[0],
                PW[1],
                "2026-10-01",
                "2027-03-31",
                [("PW-TEAM", "Pagewise Team seat", "13.00", 60)],
                signed="Dev Malhotra, Engineering Manager",
            )
        },
    )
    mail(
        b,
        "206_pagewise_oct",
        "2026-10-01T08:00:00",
        PW[2],
        AP,
        "Invoice INV-PW-120",
        "Invoice attached.\n",
        {
            "INV-PW-120.csv": invoice(
                "INV-PW-120",
                PW[0],
                "2026-10-01",
                "2026-10-31",
                [("PW-TEAM", "Team seat", "2026-10-01", "2026-10-31", 60, "13.00", "780.00")],
            )
        },
    )
    mail(
        b,
        "207_cloudkeep_oct",
        "2026-10-02T08:00:00",
        CK[2],
        AP,
        "Invoice INV-CK-402",
        "Invoice attached.\n",
        {
            "INV-CK-402.csv": invoice(
                "INV-CK-402",
                CK[0],
                "2026-10-02",
                "2026-11-01",
                [
                    (
                        "CK-STORE-TB",
                        "Backup storage",
                        "2026-10-01",
                        "2026-10-31",
                        40,
                        "21.50",
                        "860.00",
                    )
                ],
            )
        },
    )
    # Decoy: billed at the amended $19.00, which supersedes the earlier $18.00 email.
    mail(
        b,
        "208_tallyhub_oct",
        "2026-10-01T08:30:00",
        TH[2],
        AP,
        "Invoice INV-TH-210",
        "Invoice attached.\n",
        {
            "INV-TH-210.csv": invoice(
                "INV-TH-210",
                TH[0],
                "2026-10-01",
                "2026-10-31",
                [("TH-SEAT", "Seat", "2026-10-01", "2026-10-31", 30, "19.00", "570.00")],
            )
        },
    )
    mail(
        b,
        "209_tallyhub_notice",
        "2026-10-28T09:00:00",
        TH[2],
        PRIYA,
        "November invoice",
        "Hi Priya, your November invoice reflects amendment AM-2026-11, which adds reporting to "
        "every seat.\n",
    )
    mail(
        b,
        "210_tallyhub_nov",
        "2026-11-01T08:30:00",
        TH[2],
        AP,
        "Invoice INV-TH-233",
        "Invoice attached.\n",
        {
            "INV-TH-233.csv": invoice(
                "INV-TH-233",
                TH[0],
                "2026-11-01",
                "2026-11-30",
                [("TH-SEAT", "Seat", "2026-11-01", "2026-11-30", 30, "22.00", "660.00")],
            )
        },
    )
    mail(
        b,
        "211_ap_status",
        "2026-11-10T09:00:00",
        AP,
        PRIYA,
        "AP status",
        "Monthly AP status: all vendor invoices through November are entered.\n",
    )


def main() -> None:
    for folder in ROOT.glob("batch_*"):  # keep EXPECTED.md and anything else hand-written
        shutil.rmtree(folder)
    batch_01()
    batch_02()
    batch_03()
    (ROOT / "authority.toml").write_text(AUTHORITY, encoding="utf-8", newline="\n")
    print(f"wrote {sum(1 for _ in ROOT.rglob('*.eml'))} emails to {ROOT}")


if __name__ == "__main__":
    main()
