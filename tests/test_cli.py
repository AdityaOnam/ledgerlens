import importlib.util
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
    assert "Extractor: layout reader (ANTHROPIC_API_KEY not set)" in capsys.readouterr().out


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
