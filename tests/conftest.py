import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Keep tests independent of the developer's real provider settings.
    for var in ("CLARIVANCE_PROVIDER", "CLARIVANCE_MODEL", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
