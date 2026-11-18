# Roadmap

Built in small, reviewable steps. Each day ends with green tests.

| Day | Milestone | Status |
|---|---|---|
| 1 | Domain model (money, facts, findings), mailbox ingest for `.eml` + text/CSV attachments, on-disk term memory, all seven detectors, action policy, CLI, JSON/Markdown report, sample mailbox, unit tests | done |
| 2 | LLM extractor: Claude turns free-form PDFs and emails into typed facts with verbatim quotes; grounding check rejects any quote not found on the page; response cache on disk | done |
| 3 | PDF and XLSX parsers, OCR fallback for scanned invoices, completeness check (invoice lines vs. printed total) | done |
| 4 | Conflict and cannot_determine reasoning across sources; precedence rules (signed amendment > order form > email); authority check on who may agree terms | done |
| 5 | Feedback loop: a reviewer's answer to an escalation is stored and applied to later batches (one-off vs. standing) | done |
| 6 | Synthetic mailbox generator with an independent oracle; eval runner with precision, recall and dollars recovered vs. wrongly claimed | |
| 7 | CI (lint, types, tests), docs polish, demo report, v0.1.0 release | |
