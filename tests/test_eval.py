"""The eval runner: the layout reader scores perfectly, and a broken reader is caught."""

import json
from dataclasses import replace

import pytest

from ledgerlens.evaluate.runner import evaluate, parse_seeds, to_markdown, write
from ledgerlens.ingest.extract import extract


def test_layout_reader_agrees_with_the_oracle(tmp_path):
    ev = evaluate(range(1, 9), tmp_path)
    t = ev.total
    assert t.tp > 50 and t.fp == t.fn == 0 and not t.wrong_amounts
    assert t.recovered == t.at_stake > 0 and t.wrongly_claimed == 0
    assert len(t.by_class()) == 7


def drop_cancellations(documents, domains):
    x = extract(documents, domains)
    x.cancellations.clear()
    return x


def forget_true_up(documents, domains):
    x = extract(documents, domains)
    x.agreements = [replace(a, true_up_allowed=False) for a in x.agreements]
    return x


def test_a_reader_that_misses_cancellations_loses_recall(tmp_path):
    t = evaluate(range(1, 9), tmp_path, extractor=drop_cancellations).total
    assert t.recall < 1.0 and t.precision == 1.0
    assert {e.cls for e in t.missed} == {"billed_after_cancel"}
    assert t.recovered < t.at_stake and t.wrongly_claimed == 0


def test_a_reader_that_misreads_true_up_claims_money_wrongly(tmp_path):
    t = evaluate(range(1, 9), tmp_path, extractor=forget_true_up).total
    assert t.precision < 1.0 and t.recall == 1.0
    assert {str(f.cls) for f in t.spurious} == {"seats_over_licensed"}
    assert t.wrongly_claimed > 0


def test_report_lists_disagreements(tmp_path):
    ev = evaluate([3], tmp_path / "w", extractor=drop_cancellations, described="broken reader")
    md = to_markdown(ev)
    assert "read by the broken reader" in md and "## Disagreements" in md
    assert "missed `billed_after_cancel`" in md
    j, m = write(ev, tmp_path / "out")
    data = json.loads(j.read_text(encoding="utf-8"))
    assert data["total"]["false_negatives"] == len(ev.total.missed) > 0
    assert data["scenarios"][0]["missed"][0]["cls"] == "billed_after_cancel"
    assert m.read_text(encoding="utf-8") == md


@pytest.mark.parametrize(
    ("text", "seeds"), [("7", [7]), ("1-3", [1, 2, 3]), ("1, 4,9-10", [1, 4, 9, 10])]
)
def test_parse_seeds(text, seeds):
    assert parse_seeds(text) == seeds


@pytest.mark.parametrize("text", ["", "5-2", "x"])
def test_parse_seeds_refuses_nonsense(text):
    with pytest.raises(ValueError):
        parse_seeds(text)
