import importlib.util
import json
from pathlib import Path

import pytest

from ledgerlens.cli import choose_extractor, main
from ledgerlens.ingest.extract import extract

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "acme"
HAS_SDK = importlib.util.find_spec("anthropic") is not None


def test_auto_falls_back_to_layout_without_a_key(tmp_path):
    extractor, described = choose_extractor("auto", tmp_path, env={})
    assert extractor is extract and "ANTHROPIC_API_KEY not set" in described


def test_layout_is_layout_even_with_a_key(tmp_path):
    extractor, _ = choose_extractor("layout", tmp_path, env={"ANTHROPIC_API_KEY": "test"})
    assert extractor is extract


def test_llm_without_a_key_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        choose_extractor("llm", tmp_path, env={})


@pytest.mark.skipif(HAS_SDK, reason="anthropic is installed")
def test_llm_without_the_sdk_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match=r"ledgerlens\[llm\]"):
        choose_extractor("llm", tmp_path, env={"ANTHROPIC_API_KEY": "test"})


@pytest.mark.skipif(not HAS_SDK, reason="anthropic not installed")
def test_llm_with_key_and_sdk_builds_the_extractor_without_calling(tmp_path):
    from ledgerlens.ingest.llm import LLMExtractor

    extractor, described = choose_extractor("llm", tmp_path, env={"ANTHROPIC_API_KEY": "test"})
    assert isinstance(extractor, LLMExtractor) and "claude-sonnet-5-5" in described


def test_cli_reports_which_extractor_ran(tmp_path, capsys):
    args = ["audit", str(SAMPLES), "--state", str(tmp_path / "s"), "--out", str(tmp_path / "o")]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Extractor: layout reader (ANTHROPIC_API_KEY not set)" in out
    assert "Authority: 1 signatory(ies) from" in out and "authority.toml" in out


def test_authority_file_is_found_next_to_the_mailbox(tmp_path):
    from ledgerlens.cli import choose_authority

    assert choose_authority(tmp_path, None) == (None, "not checked (no authority.toml)")
    (tmp_path / "authority.toml").write_text(
        '[[signatory]]\nname = "Ada"\nemail = "ada@acme.test"\n', encoding="utf-8"
    )
    authority, described = choose_authority(tmp_path, None)
    assert authority.may_agree("ada@acme.test") and described.startswith("1 signatory(ies)")


def test_bad_authority_file_is_a_clear_error(tmp_path, capsys):
    bad = tmp_path / "auth.toml"
    bad.write_text("[[signatory]]\nname = 'Ada'\n", encoding="utf-8")
    box = tmp_path / "box"
    box.mkdir()
    for path in (bad, tmp_path / "missing.toml"):
        with pytest.raises(SystemExit):
            main(["audit", str(box), "--state", str(tmp_path / "s"), "--authority", str(path)])
        assert "authority file:" in capsys.readouterr().err


def test_synth_writes_a_mailbox_and_its_truth(tmp_path, capsys):
    folder = tmp_path / "mb"
    assert main(["synth", str(folder), "--seed", "4", "--vendors", "3", "--months", "4"]) == 0
    truth = json.loads((folder / "TRUTH.json").read_text(encoding="utf-8"))
    assert sorted(p.name for p in folder.iterdir()) == ["TRUTH.json", "batch_01", "batch_02"]
    assert f"{len(truth)} expected finding(s)" in capsys.readouterr().out


def test_synth_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["synth", str(tmp_path)])
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_eval_reports_and_passes_its_bars(tmp_path, capsys):
    out = tmp_path / "o"
    code = main(
        ["eval", "--seeds", "1-3", "--out", str(out), "--min-precision", "1", "--min-recall", "1"]
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "Precision 100.0%  recall 100.0%" in printed and "$0.00 wrongly claimed" in printed
    assert (out / "eval.md").exists() and (out / "eval.json").exists()


def test_eval_keeps_mailboxes_in_work(tmp_path):
    work = tmp_path / "w"
    assert main(["eval", "--seeds", "2", "--work", str(work), "--out", str(tmp_path / "o")]) == 0
    assert (work / "seed_2" / "mailbox" / "batch_01").is_dir()


def test_eval_fails_when_a_bar_is_missed(tmp_path, monkeypatch, capsys):
    from ledgerlens.evaluate import runner

    real = runner.evaluate

    def broken(seeds, work, *args, **kwargs):
        def reader(documents, domains):
            x = extract(documents, domains)
            x.cancellations.clear()
            return x

        kwargs["extractor"] = reader
        return real(seeds, work, *args, **kwargs)

    monkeypatch.setattr(runner, "evaluate", broken)
    code = main(["eval", "--seeds", "1-4", "--out", str(tmp_path / "o"), "--min-recall", "1"])
    assert code == 1 and "FAILED: recall" in capsys.readouterr().err


def test_eval_rejects_bad_seeds(tmp_path):
    with pytest.raises(SystemExit):
        main(["eval", "--seeds", "9-1", "--out", str(tmp_path)])
