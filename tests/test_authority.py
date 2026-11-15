import pytest

from ledgerlens.rules.authority import Authority, AuthorityError, find

TEXT = """
# who may agree terms
[[signatory]]
name = "Priya Raman"
email = "Priya.Raman@acme.test"

[[signatory]]
name = "Omar  Haddad"
email = "omar@acme.test"
"""


def test_signatory_is_matched_by_name_ignoring_title_case_and_spacing():
    auth = Authority.parse(TEXT)
    assert auth.may_sign("Priya Raman, VP Finance")
    assert auth.may_sign("omar haddad")
    assert not auth.may_sign("Dev Malhotra, Engineering Manager")
    assert not auth.may_sign("")


def test_email_agreement_is_matched_by_address():
    auth = Authority.parse(TEXT)
    assert auth.may_agree("priya.raman@acme.test")
    assert not auth.may_agree("dev@acme.test")
    assert auth.contact == "priya.raman@acme.test"


@pytest.mark.parametrize(
    "text",
    [
        "[[signatory]]\nname = 'No Email'\n",
        "[[signatory]]\nname = 'X'\nemail = 'not-an-address'\n",
        "signatory = 'Priya'\n",
        "[[signatory\n",
    ],
)
def test_malformed_files_are_rejected(text):
    with pytest.raises(AuthorityError):
        Authority.parse(text)


def test_empty_list_authorises_nobody():
    auth = Authority.parse("")
    assert not auth.may_sign("Priya Raman") and auth.contact == ""


def test_file_is_found_at_the_top_of_the_mailbox(tmp_path):
    assert find(tmp_path) is None
    (tmp_path / "authority.toml").write_text(TEXT, encoding="utf-8")
    assert find(tmp_path) == tmp_path / "authority.toml"
    assert len(Authority.load(find(tmp_path)).signatories) == 2
