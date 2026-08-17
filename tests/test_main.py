"""The command line reports a delivery problem instead of a traceback."""

import sys
from pathlib import Path

import pytest

from infomentor_digest import main as main_module
from infomentor_digest.main import main
from infomentor_digest.state import Store


@pytest.fixture
def login(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured login, which every command but `setup` needs."""
    monkeypatch.setenv("INFOMENTOR_USERNAME", "user")
    monkeypatch.setenv("INFOMENTOR_PASSWORD", "secret")


def command(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(sys, "argv", ["infomentor-digest", name])


def test_test_notify_reports_that_no_channel_is_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], login: None
) -> None:
    command(monkeypatch, "test-notify")

    assert main() == 1
    assert "no delivery channel configured" in capsys.readouterr().err


def test_test_notify_says_sent_when_a_channel_took_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], login: None
) -> None:
    monkeypatch.setattr(main_module, "send", lambda *_: None)
    command(monkeypatch, "test-notify")

    assert main() == 0
    assert capsys.readouterr().out.strip() == "sent"


def test_forget_drops_the_reported_facts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    login: None,
) -> None:
    """A reader who lost track of what the digest remembers can start over."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    store = Store.load(tmp_path / "reported.json")
    store.add("telegram", 1, {"news:1", "news:2"})
    store.save()
    command(monkeypatch, "forget")

    assert main() == 0
    assert "forgot 2 facts" in capsys.readouterr().out
    assert not (tmp_path / "reported.json").exists()


def test_forget_says_so_when_there_was_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    login: None,
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    command(monkeypatch, "forget")

    assert main() == 0
    assert "forgot 0 facts" in capsys.readouterr().out


def test_setup_asks_before_the_login_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The questions must run although `.env` holds nothing yet."""
    asked: list[str] = []
    monkeypatch.setattr(main_module, "setup", lambda path: asked.append(str(path)))
    command(monkeypatch, "setup")

    assert main() == 0
    assert asked == [".env"]
