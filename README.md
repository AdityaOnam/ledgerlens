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

## Actions and safety

| Mode | Behaviour |
|---|---|
| `supervised` | Nothing is executed; every finding is a recommendation |
| `autonomous` | Low-risk findings under the threshold are actioned; everything else goes to a person |

Conflicts, cannot_determine items and anything at or above the review threshold (default $2,500)
always go to human review.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
ledgerlens audit data/samples/acme --mode supervised
pytest
```

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
  (cancellations, credit promises) are matched to a vendor by email domain, never by what the
  model says.

The grounding check proves that a quote is in the document. It cannot prove the document is
honest: text planted in a document can still be quoted. That is why every finding shows its
quotes, and why the action policy decides what happens next, not the model.

## Layout

```
src/ledgerlens/
  domain/    money, dates, typed facts and findings
  ingest/    mailbox reader, layout parser, LLM extractor, grounding check, cache
  store/     on-disk memory of agreed terms, carried across batches
  rules/     one detector per finding class
  decide/    action policy (supervised / autonomous)
  report/    JSON and Markdown reports
data/samples one synthetic mailbox per fictional company
docs/        design notes and decision log
```

See [docs/ROADMAP.md](docs/ROADMAP.md) for what's built and what's next.

All companies, people and numbers in `data/` are invented.

## License

MIT
