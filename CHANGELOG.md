# Changelog

## 0.1.0 (2026-11-23)

First release. Everything in data/ is invented.

**Reading**
- Mailboxes of `.eml` files in batches; attachments as text, CSV, PDF (text layer), XLSX and,
  with Tesseract, scanned PDFs and images. Optional extras: `pdf`, `xlsx`, `ocr`, `llm`.
- A layout reader for order forms, amendments, CSV and printed invoices, with no model involved.
- An optional Claude reader for free-form documents. Every fact must carry a quote found in the
  document word for word; anything else is rejected and listed. Responses are cached on disk.

**Deciding**
- Seven finding classes: `price_over_contract`, `seats_over_licensed`, `uplift_over_cap`,
  `billed_after_cancel`, `duplicate_charge`, `credit_not_applied`, `renewal_notice_due`; plus
  `conflict` and `cannot_determine` when the sources disagree or a document is missing.
- Completeness check: invoice lines minus credits must equal the printed total.
- Term precedence (signed amendment > order form > agreed email) and an authority file naming
  who may agree terms.
- Action policy: `supervised` executes nothing; `autonomous` actions only low-risk findings under
  the review threshold (default $2,500). Conflicts and renewal notices always go to a person.
- Reviewers answer findings once or standing (`dismiss`, `approve`, `price`); answers are kept
  in a decision log and applied to later batches.

**Measuring**
- A seeded synthetic mailbox generator, an independent oracle and `ledgerlens eval`, reporting
  precision, recall and dollars recovered vs. wrongly claimed.

**Project**
- CI: ruff, mypy, pytest on Python 3.11-3.13 and Windows, sample and demo drift checks, and an
  eval gate on 20 seeds.
- Demo reports of the sample mailbox in [docs/demo](docs/demo).
- `ledgerlens --version`.
