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

## Layout

```
src/ledgerlens/
  domain/    money, dates, typed facts and findings
  ingest/    mailbox reader and document parsers
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
