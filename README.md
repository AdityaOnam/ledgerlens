# Ledgerlens

**Find the money leaking out of your SaaS and cloud bills.**

Companies pay dozens of software vendors every month. Contracts promise seat prices, renewal caps
and service credits; emails cancel add-ons and agree discounts. Invoices quietly ignore all of it.
Ledgerlens reads the contracts, order forms, emails and invoices, remembers what was agreed, and
flags every line that disagrees, with the exact quote that proves it.

## Design in one line

**The model reads, the code decides.** Documents are turned into typed facts, each carrying a
verbatim quote and its source. Deterministic Python then prices every line, applies the contract's
rules and picks an action. Every finding can be traced to a quote and the rule that used it.

## What it catches

| Class | Example |
|---|---|
| `price_over_contract` | Seats billed at $45 when the order form says $38 |
| `seats_over_licensed` | 140 seats billed on a 120-seat plan without a true-up clause |
| `uplift_over_cap` | Renewal price raised 12 % when the contract caps uplift at 7 % |
| `billed_after_cancel` | An add-on cancelled by email, still billed next cycle |
| `duplicate_charge` | The same subscription period billed on two invoices |
| `credit_not_applied` | An SLA credit the vendor confirmed, missing after 60 days |
| `renewal_notice_due` | Auto-renewal whose notice deadline falls in the next 45 days |

Two behaviours cut across all of them:

- **conflict**: two trusted sources disagree (e.g. order form vs. a later email); a person decides.
- **cannot_determine**: the answer depends on a document Ledgerlens does not have; it says which one.
  This includes invoices whose lines and credits do not add up to the printed total: a line may
  have been lost in reading, or the vendor's total may be wrong, and the code will not guess which.
  It also covers an overcharge from a vendor whose documents cite an order form or amendment that
  was never received, and an invoice that follows terms agreed by someone without authority.

## Which term wins

A price can be stated by a signed amendment, by the signed order form it amends, or by an email
in which the vendor and the customer agree it. They rank in that order:

| Situation | Result |
|---|---|
| Amendment in force | Its price replaces the order form's, from its effective date |
| Two amendments effective the same day, different prices | `conflict` |
| Email agreed price, effective on or before the signed term in force | Superseded by the signed term |
| Email agreed price, effective later, different from the signed term | `conflict`: the deal may never have been papered |
| Email agreed price for a SKU no signed document covers | Governs on its own |

A conflict is only reported when it costs money: if the invoice already bills the lowest
price any source states, there is nothing to decide.

**Who may agree terms.** Put an `authority.toml` at the top of the mailbox (or pass
`--authority FILE`):

```toml
[[signatory]]
name = "Priya Raman"
email = "priya.raman@acme-robotics.com"
```

With it, an agreement binds only if its `Signed:` line names a listed signatory, and an emailed
price binds only if the customer-side address on the email is listed. Unsigned agreements do
not bind. Terms that do not bind are not used to price anything. If an invoice follows one
anyway (say 60 seats on an amendment an engineering manager signed, when the binding terms allow
50), the line is `cannot_determine` and the first signatory is asked to sign off. It is not
disputed, because a colleague may really have agreed it. Without the file, no authority check is
made, and the console says so.

## Actions and safety

| Mode | Behaviour |
|---|---|
| `supervised` | Nothing is executed; every finding is a recommendation |
| `autonomous` | Low-risk findings under the threshold are actioned; everything else goes to a person |

Conflicts, cannot_determine items and anything at or above the review threshold (default $2,500)
always go to human review.

## Answering escalations

Every finding has an 8-character id, shown on the console and in the report. A reviewer answers
it, and the answer is applied from the next audit on:

```bash
ledgerlens review 7a31e82a price --price 19.50 --standing --by "Priya Raman" --note "email deal stands"
ledgerlens review 3f0c9e21 dismiss --by "Priya Raman"          # this finding only
ledgerlens review 51be0a7d approve --standing --by "Priya Raman" --up-to 1000
ledgerlens decisions                                           # list them
ledgerlens review 51be0a7d --revoke                            # withdraw
```

| Answer | Once (default) | `--standing` |
|---|---|---|
| `dismiss` | That finding is closed, no action | Later findings of the same class, vendor, SKU and rule are closed too |
| `approve` | Its action goes ahead even above the review threshold; an approved conflict is disputed down to the lowest price | Same for later findings of that kind |
| `price` (conflicts only) | The named price governs that line | The named price governs later invoices for that vendor and SKU, so they are priced against it instead of escalating again |

- A standing `dismiss` or `approve` covers later findings only up to `--up-to` (by default the
  amount of the finding answered). A bigger one is reported as usual, with a note saying why.
- The price must be one of the prices in conflict, and a standing price only settles a later
  conflict between the same prices. A new amendment that changes the picture escalates again.
- Conflicts and renewal notices cannot be approved standing: a conflict is settled by naming
  its price, and each renewal is its own decision.
- Supervised mode still executes nothing, approved or not. The reviewer's name and date are
  kept with every decision, and a price ruling is cited as evidence in the findings it prices.
- Decisions are stored in `decisions.json` in the state directory. `audit --reset` forgets the
  batches but keeps the decisions, so a mailbox audited again from scratch is answered the same
  way; a one-off decision applies again to the same finding there, and to nothing else.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
ledgerlens audit data/samples/acme --mode supervised
pytest
```

## What it reads

Emails (`.eml`) and their attachments:

| Attachment | How | Install |
|---|---|---|
| `.txt`, `.csv`, `.md` | as text | built in |
| `.pdf` | the text layer of each page; pages without one are treated as scans | `pip install -e ".[pdf]"` |
| `.xlsx`, `.xlsm` | every sheet as CSV, so a spreadsheet invoice reads like a CSV one | `pip install -e ".[xlsx]"` |
| `.png`, `.jpg`, `.tif`, scanned PDF pages | OCR with Tesseract | `pip install -e ".[ocr]"` plus the [Tesseract](https://github.com/tesseract-ocr/tesseract) binary |

Invoices are understood as CSV (`invoice_id,...` rows) or as a printed layout (`INVOICE <id>`,
`Issued:` / `Due:` fields, a `| SKU | Description | Period | Qty | Unit price | Amount |` table
and a `Total due:` line), which is what comes out of most PDFs and scans. Anything else can be
read by Claude (below).

`--ocr auto` (default) uses Tesseract when it is installed; `--ocr off` never does. A scan that
cannot be read is skipped with a note in the report, never guessed at. Every invoice, however it
was read, must add up: lines minus applied credits must equal the printed total.

## Reading free-form documents with Claude

Well-formed order forms and CSV invoices are read by a layout parser, with no model involved.
Documents it cannot parse (a prose order confirmation, an email that agrees terms in its own
words) can be read by Claude instead:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY = "..."
ledgerlens audit data/samples/acme --extractor llm
```

- `--extractor auto` (default) uses Claude only when `ANTHROPIC_API_KEY` is set and the
  `anthropic` package is installed, and otherwise uses the layout parser on its own.
  `--extractor layout` never calls a model.
- The model answers in a strict JSON schema, and every fact must include a verbatim quote.
  A fact is kept only if its quote appears in the document word for word and its identifier
  and amount appear inside that quote. Rejected facts are listed as notes in the report.
- Responses are cached in `.cache/llm` (change it with `--cache`), keyed by model, prompt
  and document. Re-running an audit makes no new calls.
- The default model is `claude-sonnet-5-5` (change it with `--model`). Email statements
  (cancellations, credit promises, agreed prices) are matched to a vendor by email domain, and
  who agreed a price is read from the email's addresses, never from what the model says. A
  signatory the model reports but the document does not print is dropped.

The grounding check proves that a quote is in the document. It cannot prove the document is
honest: text planted in a document can still be quoted. That is why every finding shows its
quotes, and why the action policy decides what happens next, not the model.

## Measuring it

The sample mailbox shows a handful of cases. To measure Ledgerlens on many, generate invented
mailboxes whose right answers are known in advance and score the audit against them:

```bash
ledgerlens eval --seeds 1-50                     # writes out/eval/eval.md and eval.json
ledgerlens synth my-mailbox --seed 7             # one mailbox, plus TRUTH.json to look at
```

- Each seed invents a customer, up to twelve vendors and some months of order forms, CSV and
  printed invoices, cancellations and credit promises, split into batches. Problems are planted
  at random: overcharged seats, seats over the licence (and decoys where true-up allows them),
  add-ons billed after cancellation, months billed twice, credits never applied, totals that do
  not add up, renewals coming due, and vendors with no order form at all. The same seed always
  gives the same mailbox, byte for byte.
- An **oracle** works out what the audit must find from the invented world itself, never from
  the mailbox, and imports nothing from Ledgerlens' readers or rules (a test checks this). It
  replays the batches as the audit does, so a problem is expected in the first batch whose
  documents prove it.
- The audit is the real one, batch by batch. A finding matches an expected one when class,
  vendor, invoice, SKU and reference agree. The report gives precision and recall, overall and
  per class, and three dollar figures over the classes that claim money back:
  **at stake** (what is owed), **recovered** (what the audit claimed of it) and **wrongly
  claimed** (claimed but not owed, including the excess on a right finding with the wrong
  amount). Every disagreement is listed.
- `--vendors`, `--months` and `--batches` shape the mailboxes; `--extractor llm` scores the
  Claude reader instead of the layout reader; `--work DIR` keeps the mailboxes;
  `--min-precision` and `--min-recall` make the command exit 1 below a bar.

On seeds 1-50 the layout reader finds all 605 planted problems with no false findings and
nothing wrongly claimed. Conflicts, amendments, emailed prices and authority are not generated
yet; the sample mailbox covers them.

## Layout

```
src/ledgerlens/
  domain/    money, dates, typed facts and findings
  ingest/    mailbox reader, PDF/XLSX/OCR conversion, layout parser, LLM extractor,
             grounding check, cache
  store/     on-disk memory of agreed terms and reviewers' decisions, carried across batches
  rules/     one detector per finding class, term precedence, who may agree terms
  decide/    action policy (supervised / autonomous), reviewers' decisions
  report/    JSON and Markdown reports
  evaluate/  synthetic mailbox generator, independent oracle, scoring and eval runner
data/samples one synthetic mailbox per fictional company
docs/        design notes and decision log
```

See [docs/ROADMAP.md](docs/ROADMAP.md) for what's built and what's next.

All companies, people and numbers in `data/` are invented.

## License

MIT
