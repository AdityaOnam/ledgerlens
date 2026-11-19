"""The synthetic mailbox generator: deterministic, readable, and dated as the oracle assumes."""

import pytest

from ledgerlens.evaluate.synth import BASE, generate, write_mailbox
from ledgerlens.ingest.extract import extract
from ledgerlens.ingest.mailbox import read_mailbox


def _bytes(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*.eml")}


def test_same_seed_gives_a_byte_identical_mailbox(tmp_path):
    write_mailbox(generate(11), tmp_path / "a")
    write_mailbox(generate(11), tmp_path / "b")
    assert _bytes(tmp_path / "a") == _bytes(tmp_path / "b")


def test_different_seeds_give_different_mailboxes(tmp_path):
    write_mailbox(generate(1), tmp_path / "a")
    write_mailbox(generate(2), tmp_path / "b")
    assert _bytes(tmp_path / "a") != _bytes(tmp_path / "b")


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_every_batch_is_dated_at_its_cutoff_and_fully_readable(tmp_path, seed):
    world = generate(seed)
    write_mailbox(world, tmp_path)
    batches = read_mailbox(tmp_path)
    assert [b.as_of for b in batches] == world.cutoffs
    domains: dict[str, str] = {}
    invoices = 0
    for b in batches:
        assert not b.skipped
        x = extract(b.documents, domains)
        assert not x.unread
        domains.update(x.vendor_domains)
        invoices += len(x.invoices)
    assert invoices == sum(len(v.bills) for v in world.vendors)


def test_names_codes_and_invoice_ids_are_unique():
    for seed in range(30):
        world = generate(seed, vendors=12)
        assert len({v.name for v in world.vendors}) == 12
        assert len({v.code for v in world.vendors}) == 12
        ids = [b.invoice_id for v in world.vendors for b in v.bills]
        assert len(ids) == len(set(ids))


def test_shape_follows_the_arguments():
    world = generate(5, vendors=3, months=4, batches=4)
    assert len(world.vendors) == 3 and len(world.cutoffs) == 4
    assert world.cutoffs[0].month == BASE.month and world.cutoffs[-1].day == 25
    contracted = [v for v in world.vendors if v.contract]
    assert all(len([b for b in v.bills if not b.corrected_copy]) == 4 for v in contracted)


@pytest.mark.parametrize(
    "kwargs", [{"vendors": 0}, {"vendors": 13}, {"months": 2, "batches": 3}, {"batches": 0}]
)
def test_bad_shapes_are_refused(kwargs):
    with pytest.raises(ValueError):
        generate(1, **kwargs)


def test_planted_problems_cover_every_kind_over_a_few_seeds():
    worlds = [generate(s) for s in range(1, 21)]
    vendors = [v for w in worlds for v in w.vendors]
    assert any(v.contract is None for v in vendors)
    assert any(v.cancels for v in vendors)
    assert any(v.credits for v in vendors)
    assert any(b.corrected_copy for v in vendors for b in v.bills)
    assert any(b.total_error for v in vendors for b in v.bills)
    assert any(v.printed for v in vendors) and any(not v.printed for v in vendors)
