import pytest


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    """Tests never reach the network, even on a machine where a real key is exported."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
