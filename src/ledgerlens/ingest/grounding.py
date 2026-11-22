"""Turn a model's JSON reading of one document into typed facts, keeping only what is grounded.

The model is asked to quote, verbatim, the passage each fact comes from. Before a fact is
trusted, the code checks that:

* the quote really occurs in the document text (whitespace inside a line is not reflowed;
  only line endings are normalised), and
* the identifier of the fact (agreement or invoice number, credit reference) and its amount
  are visible inside that quote. SKUs are not required there: free-form prose says "editor
  seats", and mapping that to a SKU is exactly the reading the model is for.

Anything that fails is dropped and reported as a note, never silently repaired. An invoice
with any ungrounded line is dropped whole, because a partial invoice would mislead the
detectors more than a missing one.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from ledgerlens.domain.dates import parse_date
from ledgerlens.domain.models import (
    Agreement,
    AppliedCredit,
    Cancellation,
    CreditPromise,
    DocumentReference,
    Evidence,
    Invoice,
    InvoiceLine,
    PriceStatement,
    PriceTerm,
)
from ledgerlens.domain.money import money, percent
from ledgerlens.ingest.extract import Extraction, customer_party, email_vendor
from ledgerlens.ingest.mailbox import Document

MIN_QUOTE = 8


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


_S = {"type": "string"}
_I = {"type": "integer"}
_B = {"type": "boolean"}

# Strict JSON schema for structured output. Optional values are "" rather than null, dates are
# YYYY-MM-DD, money is a plain decimal string. Every fact carries a verbatim `quote`.
SCHEMA: dict[str, Any] = _obj(
    {
        "agreements": _arr(
            _obj(
                {
                    "agreement_id": _S,
                    "vendor": _S,
                    "vendor_contact_email": _S,
                    "start": _S,
                    "end": _S,
                    "auto_renew": _B,
                    "notice_days": _I,
                    "uplift_cap_percent": _S,
                    "true_up_allowed": _B,
                    "amends": _S,
                    "effective": _S,
                    "signed_by": _S,
                    "quote": _S,
                    "prices": _arr(
                        _obj(
                            {
                                "sku": _S,
                                "description": _S,
                                "unit_price": _S,
                                "licensed_qty": _I,
                                "quote": _S,
                            }
                        )
                    ),
                }
            )
        ),
        "invoices": _arr(
            _obj(
                {
                    "invoice_id": _S,
                    "vendor": _S,
                    "issued": _S,
                    "due": _S,
                    "total": _S,
                    "quote": _S,
                    "lines": _arr(
                        _obj(
                            {
                                "sku": _S,
                                "description": _S,
                                "period_start": _S,
                                "period_end": _S,
                                "qty": _I,
                                "unit_price": _S,
                                "amount": _S,
                                "quote": _S,
                            }
                        )
                    ),
                    "credits": _arr(_obj({"ref": _S, "amount": _S, "quote": _S})),
                }
            )
        ),
        "cancellations": _arr(_obj({"sku": _S, "effective": _S, "quote": _S})),
        "credit_promises": _arr(_obj({"ref": _S, "amount": _S, "quote": _S})),
        "price_agreements": _arr(_obj({"sku": _S, "unit_price": _S, "effective": _S, "quote": _S})),
        "references": _arr(
            _obj(
                {
                    "kind": {"type": "string", "enum": ["order form", "amendment"]},
                    "ref": _S,
                    "quote": _S,
                }
            )
        ),
    }
)


class Ungrounded(ValueError):
    """A fact whose quote or value cannot be found in the document."""


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def grounded(quote: str, text: str) -> bool:
    """True if ``quote`` occurs verbatim in ``text`` and is long enough to mean something."""
    q = _norm(quote).strip()
    return len(q) >= MIN_QUOTE and q in _norm(text)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def mentions_amount(quote: str, amount: Decimal) -> bool:
    """True if some number in the quote equals ``amount`` (ignoring $, commas and sign)."""
    for token in _NUMBER.findall(quote):
        try:
            if money(token) == abs(amount):
                return True
        except ValueError:
            continue
    return False


def _evidence(doc: Document, quote: str, *must_contain: str) -> Evidence:
    if not grounded(quote, doc.text):
        raise Ungrounded(f"quote not found in document: {quote[:60]!r}")
    for token in must_contain:
        if token and token not in quote:
            raise Ungrounded(f"{token!r} not in its quote")
    return Evidence(doc.doc_id, _norm(quote).strip())


def _amount(doc: Document, quote: str, value: str, *must_contain: str) -> tuple[Decimal, Evidence]:
    ev = _evidence(doc, quote, *must_contain)
    amount = money(value)
    if not mentions_amount(ev.quote, amount):
        raise Ungrounded(f"amount {amount} not in its quote")
    return amount, ev


def _signatory(doc: Document, signed_by: str, notes: list[str]) -> str:
    """The signatory, only if the document prints it; otherwise the agreement counts as
    unsigned, which the authority check treats as not binding."""
    name = signed_by.split(",")[0].strip()
    if not name:
        return ""
    if name not in _norm(doc.text):
        notes.append(f"{doc.doc_id}: dropped signatory {name!r}: not in the document")
        return ""
    return signed_by.strip()


def _agreement(doc: Document, a: dict[str, Any], notes: list[str]) -> tuple[Agreement, str]:
    ev = _evidence(doc, a["quote"], a["agreement_id"])
    prices = []
    for p in a["prices"]:
        try:
            price, pev = _amount(doc, p["quote"], p["unit_price"])
            prices.append(PriceTerm(p["sku"], p["description"], price, int(p["licensed_qty"]), pev))
        except (Ungrounded, ValueError) as exc:
            notes.append(f"{doc.doc_id}: dropped price for {p.get('sku', '?')}: {exc}")
    contact = a["vendor_contact_email"]
    domain = contact.split("@")[-1].lower() if "@" in contact else ""
    effective = a["effective"]
    agreement = Agreement(
        agreement_id=a["agreement_id"],
        vendor=a["vendor"],
        start=parse_date(a["start"] or effective),
        end=parse_date(a["end"]),
        auto_renew=bool(a["auto_renew"]),
        notice_days=int(a["notice_days"]),
        uplift_cap=percent(a["uplift_cap_percent"]) if a["uplift_cap_percent"] else None,
        true_up_allowed=bool(a["true_up_allowed"]),
        prices=tuple(prices),
        evidence=ev,
        amends=a["amends"] or None,
        effective=parse_date(effective) if effective else None,
        signed_by=_signatory(doc, a.get("signed_by", ""), notes),
    )
    return agreement, domain


def _invoice(doc: Document, inv: dict[str, Any]) -> Invoice:
    ev = _evidence(doc, inv["quote"], inv["invoice_id"])
    lines = []
    for ln in inv["lines"]:
        amount, lev = _amount(doc, ln["quote"], ln["amount"])
        lines.append(
            InvoiceLine(
                ln["sku"],
                ln["description"],
                parse_date(ln["period_start"]),
                parse_date(ln["period_end"]),
                int(ln["qty"]),
                money(ln["unit_price"]),
                amount,
                lev,
            )
        )
    credits = []
    for c in inv["credits"]:
        amount, cev = _amount(doc, c["quote"], c["amount"], c["ref"])
        credits.append(AppliedCredit(c["ref"], abs(amount), cev))
    return Invoice(
        invoice_id=inv["invoice_id"],
        vendor=inv["vendor"],
        issued=parse_date(inv["issued"]),
        due=parse_date(inv["due"]),
        lines=tuple(lines),
        credits=tuple(credits),
        total=money(inv["total"]),
        evidence=ev,
    )


def facts_from_model(
    doc: Document, data: dict[str, Any], vendor_domains: dict[str, str]
) -> Extraction:
    """Build an Extraction from the model's JSON for ``doc``, dropping ungrounded facts.

    Statements in an email (cancellations, credit promises, references) are tied to a vendor by
    the email's domains, exactly as the layout reader does; the model's opinion of who the
    vendor is is not used for them. Who agreed an emailed price is read from the addresses too."""
    out = Extraction()
    notes = out.unread

    def attempt(label: str, fn: Any) -> Any:
        try:
            return fn()
        except (Ungrounded, ValueError, KeyError, TypeError) as exc:
            notes.append(f"{doc.doc_id}: dropped {label}: {exc}")
            return None

    for a in data.get("agreements", []):
        found = attempt(
            f"agreement {a.get('agreement_id', '?')}", lambda a=a: _agreement(doc, a, notes)
        )
        if found:
            agreement, domain = found
            out.agreements.append(agreement)
            if domain and agreement.vendor:
                out.vendor_domains.setdefault(domain, agreement.vendor)
    for inv in data.get("invoices", []):
        invoice = attempt(
            f"invoice {inv.get('invoice_id', '?')}", lambda inv=inv: _invoice(doc, inv)
        )
        if invoice:
            out.invoices.append(invoice)
            if invoice.vendor and "@" in doc.sender:
                out.vendor_domains.setdefault(doc.sender.split("@")[-1].lower(), invoice.vendor)

    statements = [
        *data.get("cancellations", []),
        *data.get("credit_promises", []),
        *data.get("price_agreements", []),
        *data.get("references", []),
    ]
    vendor = email_vendor(doc, {**vendor_domains, **out.vendor_domains})
    if vendor is None:
        if statements:
            notes.append(f"{doc.doc_id}: dropped {len(statements)} statement(s): vendor unknown")
        return out
    for c in data.get("cancellations", []):
        made = attempt(
            f"cancellation {c.get('sku', '?')}",
            lambda c=c: Cancellation(
                vendor,
                c["sku"],
                parse_date(c["effective"]),
                doc.sender,
                _evidence(doc, c["quote"]),
            ),
        )
        if made:
            out.cancellations.append(made)
    for c in data.get("credit_promises", []):

        def promise(c: dict[str, Any] = c) -> CreditPromise:
            amount, ev = _amount(doc, c["quote"], c["amount"], c["ref"])
            return CreditPromise(vendor, c["ref"], amount, doc.sent, ev)

        made = attempt(f"credit {c.get('ref', '?')}", promise)
        if made:
            out.credits.append(made)
    for c in data.get("price_agreements", []):

        def agreed(c: dict[str, Any] = c) -> PriceStatement:
            amount, ev = _amount(doc, c["quote"], c["unit_price"])
            party = customer_party(doc, {**vendor_domains, **out.vendor_domains})
            return PriceStatement(vendor, c["sku"], amount, parse_date(c["effective"]), party, ev)

        made = attempt(f"price for {c.get('sku', '?')}", agreed)
        if made:
            out.prices.append(made)
    parties = (doc.sender, *doc.recipients)
    known = {**vendor_domains, **out.vendor_domains}
    holder = next((p for p in parties if p.split("@")[-1].lower() in known), doc.sender)
    for r in data.get("references", []):
        made = attempt(
            f"reference {r.get('ref', '?')}",
            lambda r=r: DocumentReference(
                vendor, r["ref"], r["kind"], holder, _evidence(doc, r["quote"], r["ref"])
            ),
        )
        if made:
            out.references.append(made)
    return out
