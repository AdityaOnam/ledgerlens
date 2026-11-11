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
    assert again.batches == ["batch_01", "batch_02"]


def test_absorbing_the_same_batch_twice_adds_nothing():
    mem = Memory()
    batch = read_mailbox(SAMPLES)[0]
    for _ in range(2):
        mem.absorb(batch.name, extract(batch.documents, mem.vendor_domains))
    assert len(mem.invoices) == 4 and mem.batches == ["batch_01"]
