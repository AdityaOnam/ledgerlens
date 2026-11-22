"""Invent a customer, its vendors and a few months of their mail, with problems planted at random.

``generate(seed)`` returns a World; ``write_mailbox(world, folder)`` writes it as batches of
``.eml`` files that the layout reader understands (order forms, CSV and printed invoices, and
the stock sentences vendors and customers use in email). The same seed always gives a
byte-identical mailbox.

What may be planted, per vendor:

- a seat line billed above the order form price;
- more seats billed than licensed (a problem only if true-up is not permitted);
- an add-on cancelled by email and billed anyway for some months (or correctly dropped);
- a "corrected copy" invoice that bills a month already billed;
- a service credit promised by email, applied on a later invoice or never;
- a printed total that does not match the lines;
- an auto-renewal whose notice deadline falls just after the last batch (or a contract that
  does not auto-renew with the same dates);
- a vendor that invoices without any order form on file.

The generator does not decide which of these are findings. That is the oracle's job.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from ledgerlens.domain.dates import add_months
from ledgerlens.evaluate.world import (
    Bill,
    Cancel,
    Contract,
    Credit,
    Line,
    Person,
    Sku,
    Vendor,
    World,
    cents,
)

BASE = date(2027, 1, 1)  # the first billed month
LOOKAHEAD_DAYS = 45  # how far ahead a renewal notice deadline counts as "due"

COMPANIES = [
    ("Kestrel Foods Ltd.", "kestrel-foods.com"),
    ("Lumio Health Inc.", "lumio-health.com"),
    ("Bramblewood Studio", "bramblewood.studio"),
    ("Harrow & Pike Logistics", "harrowpike.com"),
    ("Saltmarsh Analytics", "saltmarsh.ai"),
    ("Orchard Lane Clinics", "orchardlane.health"),
]
FIRST = ["Meera", "Tomas", "Aiko", "Bilal", "Clara", "Ravi", "Ines", "Kwame", "Sofia", "Arjun"]
LAST = ["Iyer", "Lindqvist", "Okafor", "Moreau", "Haddad", "Castillo", "Brennan", "Sato"]
NAME_A = ["Bright", "Cloud", "Page", "Flux", "Tally", "North", "Quill", "Ember", "Harbor", "Pixel",
          "Lumen", "Orbit", "Cedar", "Slate", "Vector", "Juniper"]  # fmt: skip
NAME_B = ["desk", "keep", "wise", "metrics", "hub", "stack", "forge", "line", "grid", "sync",
          "loop", "nest"]  # fmt: skip
TLDS = ["io", "com", "app", "co"]
PRODUCTS = [
    ("PRO", "Pro seat"),
    ("USER", "User licence"),
    ("TB", "Storage per TB"),
    ("SEAT", "Team seat"),
    ("AGENT", "Agent seat"),
]
ADDONS = [
    ("ANALYTICS", "Analytics add-on"),
    ("SSO", "Single sign-on"),
    ("AUDIT", "Audit log retention"),
    ("SUPPORT", "Premium support"),
]
OVERCHARGES = [Decimal(x) for x in ("0.50", "1.00", "2.00", "2.50", "4.00", "5.00")]
TOTAL_ERRORS = [Decimal(x) for x in ("10.00", "-25.50", "100.00", "-0.40", "37.25")]


def month_end(d: date) -> date:
    return add_months(d.replace(day=1), 1) - timedelta(days=1)


def _cutoffs(months: int, batches: int) -> list[date]:
    if not 1 <= batches <= months:
        raise ValueError("need at least one month per batch")
    per = -(-months // batches)
    last = [min((i + 1) * per, months) for i in range(batches)]
    return [add_months(BASE, n - 1).replace(day=25) for n in dict.fromkeys(last)]


def _money(rng: random.Random, low: int, high: int, step: str = "0.25") -> Decimal:
    s = Decimal(step)
    return cents(Decimal(rng.randint(int(low / s), int(high / s))) * s)


def _mid_month(rng: random.Random, month: date) -> date:
    return month.replace(day=rng.randint(5, 20))


def _names(rng: random.Random, n: int) -> list[tuple[str, str]]:
    """n distinct vendor names, each with a distinct 2-3 letter code."""
    pairs = rng.sample([(a, b) for a in NAME_A for b in NAME_B], n)
    out, codes = [], set()
    for a, b in pairs:
        code = (a[0] + b[0]).upper()
        if code in codes:
            code = (a[:2] + b[0]).upper()
        if code in codes:
            code = (a[0] + b[:2]).upper()
        if code in codes:  # pragma: no cover - 16 x 12 names make this practically impossible
            raise ValueError(f"could not give {a}{b} a unique code")
        codes.add(code)
        out.append((a + b, code))
    return out


def generate(seed: int, vendors: int = 6, months: int = 6, batches: int = 2) -> World:
    if not 1 <= vendors <= 12:
        raise ValueError("vendors must be between 1 and 12")
    rng = random.Random(seed)
    company, domain = rng.choice(COMPANIES)
    first, last = rng.sample(FIRST, 2), rng.sample(LAST, 2)
    signer = Person(f"{first[0]} {last[0]}", "VP Finance", f"{first[0].lower()}@{domain}")
    ap = Person("AP Team", "Accounts Payable", f"ap@{domain}")
    cutoffs = _cutoffs(months, batches)
    world = World(seed, company, domain, signer, ap, [], cutoffs)
    no_contract_left = 1 if vendors >= 3 and rng.random() < 0.5 else 0
    for i, (name, code) in enumerate(_names(rng, vendors)):
        vdomain = f"{name.lower()}.{rng.choice(TLDS)}"
        printed = rng.random() < 0.4
        if no_contract_left and i > 0 and rng.random() < 0.3:
            no_contract_left = 0
            world.vendors.append(_uncontracted(rng, name, code, vdomain, printed, months))
            continue
        world.vendors.append(_contracted(rng, name, code, vdomain, printed, months, cutoffs))
    return world


def _uncontracted(
    rng: random.Random, name: str, code: str, domain: str, printed: bool, months: int
) -> Vendor:
    """A vendor that bills without any order form ever having been received."""
    suffix, desc = rng.choice(PRODUCTS)
    sku = Sku(f"{code}-{suffix}", desc, _money(rng, 8, 60), rng.randrange(5, 60, 5))
    v = Vendor(f"{name} Inc.", code, domain, printed, None)
    first = rng.randrange(0, months)
    number = rng.randint(100, 900)
    for m in range(first, months):
        start = add_months(BASE, m)
        line = Line(sku.code, sku.description, start, month_end(start), sku.licensed, sku.price)
        v.bills.append(Bill(f"INV-{code}-{number + m}", start, start, [line]))
    return v


def _contracted(
    rng: random.Random,
    name: str,
    code: str,
    domain: str,
    printed: bool,
    months: int,
    cutoffs: list[date],
) -> Vendor:
    suffix, desc = rng.choice(PRODUCTS)
    seat = Sku(f"{code}-{suffix}", desc, _money(rng, 8, 60), rng.randrange(10, 205, 5))
    skus = [seat]
    if rng.random() < 0.6:
        a_suffix, a_desc = rng.choice(ADDONS)
        skus.append(Sku(f"{code}-{a_suffix}", a_desc, _money(rng, 100, 900, "25"), 1))
    notice = rng.choice([30, 60, 90])
    if rng.random() < 0.4:  # notice deadline inside the look-ahead window of the last batch
        end = cutoffs[-1] + timedelta(days=rng.randint(0, LOOKAHEAD_DAYS - 1) + notice)
    else:
        end = cutoffs[-1] + timedelta(days=LOOKAHEAD_DAYS + notice + rng.randint(30, 300))
    start = BASE - timedelta(days=rng.randint(0, 200))
    contract = Contract(
        ref=f"OF-{start.year}-{rng.randint(100, 999)}",
        start=start,
        end=end,
        auto_renew=rng.random() < 0.6,
        notice_days=notice,
        true_up=rng.random() < 0.4,
        uplift_cap=rng.choice([None, "5%", "7%"]),
        skus=tuple(skus),
        sent=start - timedelta(days=rng.randint(5, 20)),
    )
    v = Vendor(f"{name} {rng.choice(['Inc.', 'Ltd.', 'GmbH'])}", code, domain, printed, contract)
    number = rng.randint(100, 900)
    addon = skus[1] if len(skus) > 1 else None

    # Cancellation of the add-on, honoured at once or only after some months.
    billed_until = months
    if addon and months > 1 and rng.random() < 0.5:
        k = rng.randint(1, months - 1)
        effective = add_months(BASE, k)
        v.cancels.append(Cancel(addon.code, effective, _mid_month(rng, add_months(BASE, k - 1))))
        billed_until = k + rng.randint(0, months - k)  # == k: honoured

    for m in range(months):
        start = add_months(BASE, m)
        qty = seat.licensed - (rng.randint(1, 5) if rng.random() < 0.2 else 0)
        lines = [
            Line(seat.code, seat.description, start, month_end(start), max(qty, 1), seat.price)
        ]
        if addon and m < billed_until:
            lines.append(
                Line(addon.code, addon.description, start, month_end(start), 1, addon.price)
            )
        v.bills.append(Bill(f"INV-{code}-{number + m}", start, start, lines))

    def seat_line(bill: Bill) -> int:
        return next(i for i, x in enumerate(bill.lines) if x.sku == seat.code)

    if rng.random() < 0.35:  # seats billed above the order form price
        bill = rng.choice(v.bills)
        i = seat_line(bill)
        bill.lines[i] = replace(
            bill.lines[i], unit_price=seat.price + rng.choice(OVERCHARGES)
        )  # fmt: skip
    if rng.random() < 0.35:  # more seats than licensed
        bill = rng.choice(v.bills)
        i = seat_line(bill)
        bill.lines[i] = replace(bill.lines[i], qty=seat.licensed + rng.randint(1, 15))
    if months > 1 and rng.random() < 0.25:  # a month billed twice
        m = rng.randrange(0, months - 1)
        original = v.bills[m]
        later = _mid_month(rng, add_months(BASE, rng.randint(m + 1, months - 1)))
        line = original.lines[seat_line(original)]
        v.bills.append(Bill(f"{original.invoice_id}A", later, later, [line], corrected_copy=True))
    if months > 1 and rng.random() < 0.35:  # a credit promised, applied later or never
        p = rng.randrange(0, months - 1)
        credit = Credit(f"CR-{code}-{rng.randint(10, 99)}", _money(rng, 50, 600, "25"),
                        _mid_month(rng, add_months(BASE, p)))  # fmt: skip
        v.credits.append(credit)
        if rng.random() < 0.5:
            v.bills[rng.randint(p + 1, months - 1)].credits.append((credit.ref, credit.amount))
    if rng.random() < 0.15:  # printed total that does not add up
        rng.choice(v.bills[:months]).total_error = rng.choice(TOTAL_ERRORS)
    return v


# --- writing the mailbox ---------------------------------------------------------------------


def order_form_text(world: World, v: Vendor) -> str:
    c = v.contract
    assert c is not None
    lines = [
        f"ORDER FORM {c.ref}",
        f"Vendor: {v.name}",
        f"Customer: {world.company}",
        f"Vendor contact: {v.contact}",
        f"Term start: {c.start.isoformat()}",
        f"Term end: {c.end.isoformat()}",
        f"Auto-renewal: {'yes' if c.auto_renew else 'no'}",
        f"Notice period: {c.notice_days} days",
    ]
    if c.uplift_cap:
        lines.append(f"Renewal uplift cap: {c.uplift_cap}")
    lines += [
        f"True-up: {'permitted at contract price' if c.true_up else 'not permitted'}",
        f"Signed: {world.signer.signature}",
        "",
        "| SKU | Description | Unit price (USD / month) | Quantity |",
    ]
    lines += [f"| {s.code} | {s.description} | {s.price:.2f} | {s.licensed} |" for s in c.skus]
    return "\n".join(lines) + "\n"


def invoice_csv(v: Vendor, b: Bill) -> str:
    out = [
        f"invoice_id,{b.invoice_id}",
        f"vendor,{v.name}",
        f"issued,{b.issued.isoformat()}",
        f"due,{(b.issued + timedelta(days=30)).isoformat()}",
        f"total,{b.printed_total:.2f}",
        "line,sku,description,period_start,period_end,qty,unit_price,amount",
    ]
    out += [
        f"line,{x.sku},{x.description},{x.start.isoformat()},{x.end.isoformat()},{x.qty},"
        f"{x.unit_price:.2f},{x.amount:.2f}"
        for x in b.lines
    ]
    out += [f"credit,{ref},{-amount:.2f}" for ref, amount in b.credits]
    return "\n".join(out) + "\n"


def invoice_printed(v: Vendor, b: Bill) -> str:
    """The text a PDF invoice gives up: header fields, a table and a total line."""
    out = [
        f"INVOICE {b.invoice_id}",
        f"Vendor: {v.name}",
        f"Issued: {b.issued.isoformat()}",
        f"Due: {(b.issued + timedelta(days=30)).isoformat()}",
        "",
        "| SKU | Description | Period | Qty | Unit price | Amount |",
    ]
    out += [
        f"| {x.sku} | {x.description} | {x.start.isoformat()} to {x.end.isoformat()} | {x.qty} "
        f"| {x.unit_price:.2f} | {x.amount:.2f} |"
        for x in b.lines
    ]
    out += [f"| Credit | {ref} | | | | {-amount:.2f} |" for ref, amount in b.credits]
    out += ["", f"Total due: {b.printed_total:.2f}"]
    return "\n".join(out) + "\n"


def _emails(world: World) -> list[tuple[date, str, str, str, str, str, dict[str, str]]]:
    """(sent, slug, from, to, subject, body, attachments) for every email in the world."""
    s = world.signer
    out = []
    for v in world.vendors:
        billing = f"{v.name.split()[0]} Billing <billing@{v.domain}>"
        slug = v.code.lower()
        c = v.contract
        if c is not None:
            out.append((c.sent, f"{slug}_order_form", billing, s.address,
                        f"Countersigned order form {c.ref}",
                        f"Hi {s.name.split()[0]}, attached is the countersigned order form.\n",
                        {f"{c.ref}.txt": order_form_text(world, v)}))  # fmt: skip
        for b in v.bills:
            name = f"{b.invoice_id}.{'txt' if v.printed else 'csv'}"
            text = invoice_printed(v, b) if v.printed else invoice_csv(v, b)
            subject = f"Invoice {b.invoice_id}" + (" (corrected copy)" if b.corrected_copy else "")
            body = (
                "Please find a corrected copy attached.\n"
                if b.corrected_copy
                else "Your invoice is attached.\n"
            )
            out.append((b.sent, f"{slug}_{b.invoice_id.lower()}", billing, world.ap.address,
                        subject, body, {name: text}))  # fmt: skip
        for x in v.cancels:
            out.append((x.sent, f"{slug}_cancel_{x.sku.lower()}", s.address, v.contact,
                        f"Cancelling {x.sku}",
                        f"Hi team,\n\nPlease cancel {x.sku} effective {x.effective.isoformat()}. "
                        f"We no longer need it.\n\n{s.name}\n", {}))  # fmt: skip
        for cr in v.credits:
            out.append((cr.sent, f"{slug}_credit_{cr.ref.lower()}",
                        f"{v.name.split()[0]} Support <support@{v.domain}>", s.address,
                        "About last month's outage",
                        "Sorry for the disruption last month. We will apply a service credit "
                        f"of ${cr.amount:.2f} to your account (ref {cr.ref}).\n", {}))  # fmt: skip
    for i, cutoff in enumerate(world.cutoffs):
        out.append((cutoff, f"zz_ap_status_{i + 1:02d}", world.ap.address, s.address,
                    "AP batch filed", "All invoices for this batch are filed.\n", {}))  # fmt: skip
    return sorted(out, key=lambda e: (e[0], e[1]))


def write_mailbox(world: World, folder: Path) -> list[Path]:
    """Write every email to ``folder/batch_NN/NNN_slug.eml``; returns the paths written."""
    paths = []
    counters: dict[int, int] = {}
    for sent, slug, sender, to, subject, body, attachments in _emails(world):
        b = world.batch_of(sent)
        n = counters[b] = counters.get(b, 0) + 1
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        msg["Date"] = format_datetime(datetime(sent.year, sent.month, sent.day, 12, tzinfo=UTC))
        msg.set_content(body)
        for filename, text in attachments.items():
            msg.add_attachment(
                text, subtype="csv" if filename.endswith(".csv") else "plain", filename=filename
            )
        if msg.is_multipart():
            msg.set_boundary(f"==ledgerlens-synth-{slug}==")  # fixed, for byte-identical output
        path = folder / world.batch_name(b) / f"{(b + 1) * 100 + n:03d}_{slug}.eml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(msg.as_bytes())
        paths.append(path)
    return paths
