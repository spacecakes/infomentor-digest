from pathlib import Path

import pytest

from infomentor_digest.config import Settings


@pytest.fixture(autouse=True)
def own_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings come from the test, never from the developer's `.env` or shell.

    Without this, a filled-in `.env` gives every test a live delivery channel.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings with no channel, so a test that forgets to fake `send` fails loudly."""
    return Settings(
        infomentor_username="user",
        infomentor_password="secret",
        data_dir=tmp_path,
    )
