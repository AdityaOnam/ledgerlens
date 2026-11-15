# Acme Robotics sample mailbox: expected findings

Invented company, vendors and people. Regenerate with `python scripts/make_samples.py`
(byte-identical output; this file is kept).

## batch_01 (as of 2026-02-10)

| Class | Vendor | Invoice / ref | Amount | Why |
|---|---|---|---|---|
| price_over_contract | Cloudkeep Ltd. | INV-CK-301 | 60.00 | 40 TB at $23.00, order form says $21.50 |
| seats_over_licensed | Brightdesk Inc. | INV-BD-1078 | 456.00 | 132 Pro seats on a 120-seat plan, true-up not permitted |
| billed_after_cancel | Brightdesk Inc. | INV-BD-1078 | 600.00 | Analytics cancelled by email effective 2026-02-01 |
| renewal_notice_due | Pagewise | OF-2025-090 | 7,200.00 | Auto-renews 2026-04-01, 30-day notice due 2026-03-01 |

Decoy: INV-CK-309 bills 44 TB on a 40 TB plan, but Cloudkeep permits true-up at contract price.
Not yet due: Cloudkeep's SLA credit was promised 2026-02-10 (grace period 60 days).

## batch_02 (as of 2026-09-15)

| Class | Vendor | Invoice / ref | Amount | Why |
|---|---|---|---|---|
| duplicate_charge | Cloudkeep Ltd. | INV-CK-301A | 860.00 | January storage billed again as a "corrected copy" |
| uplift_over_cap | Pagewise | INV-PW-077 | 30.00 | Renewed at $13.20 (+10 %), cap 5 % allows $12.60 |
| conflict | Brightdesk Inc. | INV-BD-1190 | 360.00 | AM-2026-03 ($36) and AM-2026-04 ($35) both effective 2026-06-01 |
| cannot_determine | Fluxmetrics | INV-FX-0009 | 2,400.00 | Order form OF-2026-052 cited, never received; ask ar@fluxmetrics.io |
| credit_not_applied | Cloudkeep Ltd. | SLA-2026-02 | 350.00 | Promised credit absent from both later invoices |
| renewal_notice_due | Brightdesk Inc. | OF-2025-311 | 54,720.00 | Auto-renews 2026-12-01, notice due 2026-10-01; value excludes cancelled Analytics |

Decoy: INV-BD-1102 bills 120 Pro seats at $38.00 and no Analytics, which is all correct.

## batch_03 (as of 2026-11-10)

Run with `authority.toml` (Priya Raman is the only signatory), which the CLI picks up from the
mailbox folder.

| Class | Vendor | Invoice / ref | Amount | Why |
|---|---|---|---|---|
| conflict | Cloudkeep Ltd. | INV-CK-402 | 80.00 | Signed order form says $21.50; a later email agreed $19.50 from 2026-10-01 |
| cannot_determine | Pagewise | INV-PW-120 | 150.00 | Billed 60 seats at $13.00 per AM-2026-06, signed by Dev Malhotra, who may not agree terms; the binding terms allow 50 at $12.60 |
| cannot_determine | Tallyhub | INV-TH-233 | 90.00 | Billed $22.00 against the amended $19.00; amendment AM-2026-11 is cited but was never received |

Decoy: INV-TH-210 bills $19.00, the price of signed amendment AM-2026-08, which supersedes the
$18.00 agreed by email before it took effect.

Without `authority.toml`, AM-2026-06 binds and INV-PW-120 is within its renewal cap, so batch_03
has two findings.
