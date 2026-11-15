from pathlib import Path

from ledgerlens.ingest.extract import extract
from ledgerlens.ingest.mailbox import read_mailbox
from ledgerlens.store.memory import Memory

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"


def test_round_trip_is_lossless(tmp_path):
    mem = Memory()
    for b in read_mailbox(SAMPLES):
        mem.absorb(b.name, extract(b.documents, mem.vendor_domains))
    path = tmp_path / "state" / "memory.json"
    mem.save(path)
    again = Memory.load(path)
    assert again.agreements == mem.agreements
    assert again.invoices == mem.invoices
    assert again.credits == mem.credits
    assert again.prices == mem.prices and len(again.prices) == 2
    assert {a.signed_by for a in again.agreements} == {
        "Priya Raman, VP Finance",
        "Dev Malhotra, Engineering Manager",
    }
    assert again.batches == ["batch_01", "batch_02", "batch_03"]


def test_absorbing_the_same_batch_twice_adds_nothing():
    mem = Memory()
    batch = read_mailbox(SAMPLES)[0]
    for _ in range(2):
        mem.absorb(batch.name, extract(batch.documents, mem.vendor_domains))
    assert len(mem.invoices) == 4 and mem.batches == ["batch_01"]


def test_state_saved_before_signatures_and_email_prices_still_loads(tmp_path):
    import json

    mem = Memory()
    batch = read_mailbox(SAMPLES)[0]
    mem.absorb(batch.name, extract(batch.documents, {}))
    path = tmp_path / "memory.json"
    mem.save(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("prices")
    for a in raw["agreements"]:
        a.pop("signed_by")
    path.write_text(json.dumps(raw), encoding="utf-8")
    old = Memory.load(path)
    assert old.prices == [] and {a.signed_by for a in old.agreements} == {""}
