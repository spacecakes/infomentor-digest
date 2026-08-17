"""Setup asks for what the digest needs and writes `.env`."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from infomentor_digest.setup import Chat, chats, env_text, setup

WRITTEN_BY = "# Written by ./setup.sh. Every setting is listed in env.example.\n"


def answer(monkeypatch: pytest.MonkeyPatch, replies: Mapping[str, str]) -> None:
    """Answer by what a question asks about, so one more question shifts nothing.

    A word of the prompt is the key. A question no key matches is answered with
    Enter, which takes the default the reader is shown.
    """

    def reply(prompt: str = "") -> str:
        asked = prompt.lower()
        return next((value for word, value in replies.items() if word in asked), "")

    monkeypatch.setattr("builtins.input", reply)
    monkeypatch.setattr("infomentor_digest.setup.getpass", lambda _prompt="": "secret")


def waiting(monkeypatch: pytest.MonkeyPatch, *found: Chat) -> None:
    """The chats the bot has heard from when setup asks Telegram."""
    monkeypatch.setattr("infomentor_digest.setup.read_chats", lambda _token: list(found))


def test_the_answers_become_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waiting(monkeypatch, Chat(id=-100, title="Familjen"))
    answer(monkeypatch, {"username": "user", "bot token": "token"})
    path = tmp_path / ".env"

    setup(path)

    assert path.read_text(encoding="utf-8") == (
        WRITTEN_BY + "INFOMENTOR_USERNAME=user\n"
        "INFOMENTOR_PASSWORD=secret\n"
        "TELEGRAM_BOT_TOKEN=token\n"
        "TELEGRAM_CHAT_ID=-100\n"
        "RUN_AT=18:30\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600, "the password must not be readable by all"


def test_the_reader_picks_between_two_chats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting(monkeypatch, Chat(id=1, first_name="Gabriel"), Chat(id=-100, title="Familjen"))
    answer(monkeypatch, {"username": "user", "bot token": "token", "which chat": "2"})
    path = tmp_path / ".env"

    setup(path)

    assert "TELEGRAM_CHAT_ID=-100\n" in path.read_text(encoding="utf-8")


def test_a_mail_relay_can_be_the_only_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer(
        monkeypatch,
        {
            "username": "user",
            "telegram": "n",
            "a mail relay": "y",
            "relay host": "relay",
            "digest to": "me@example.com",
            "when to report": "07:00",
        },
    )
    path = tmp_path / ".env"

    setup(path)

    assert path.read_text(encoding="utf-8") == (
        WRITTEN_BY + "INFOMENTOR_USERNAME=user\n"
        "INFOMENTOR_PASSWORD=secret\n"
        "SMTP_HOST=relay\n"
        "SMTP_PORT=25\n"
        "MAIL_TO=me@example.com\n"
        "RUN_AT=07:00\n"
    )


def test_an_env_file_that_is_already_there_is_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".env"
    path.write_text("INFOMENTOR_USERNAME=mine\n", encoding="utf-8")

    setup(path)

    assert path.read_text(encoding="utf-8") == "INFOMENTOR_USERNAME=mine\n"
    assert "keeping it" in capsys.readouterr().out


def test_an_unanswered_setting_is_left_out() -> None:
    """A missing line lets the default in `Settings` hold."""
    assert env_text({"SMTP_HOST": "relay", "MAIL_FROM": ""}) == WRITTEN_BY + "SMTP_HOST=relay\n"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"result": []}, []),
        ({"result": [{"update_id": 1}]}, []),
        (
            {"result": [{"message": {"chat": {"id": 42, "first_name": "Gabriel"}}}]},
            [(42, "Gabriel")],
        ),
        (
            {"result": [{"my_chat_member": {"chat": {"id": -100, "title": "Familjen"}}}]},
            [(-100, "Familjen")],
        ),
        (
            {
                "result": [
                    {"message": {"chat": {"id": 1, "first_name": "Gabriel"}}},
                    {"message": {"chat": {"id": 1, "first_name": "Gabriel"}}},
                    {"channel_post": {"chat": {"id": -100, "title": "Familjen"}}},
                ]
            },
            [(-100, "Familjen"), (1, "Gabriel")],
        ),
    ],
    ids=["nothing", "no chat in the update", "a person", "a group the bot joined", "newest first"],
)
def test_the_chats_that_wrote_to_the_bot(
    payload: dict[str, object], expected: list[tuple[int, str]]
) -> None:
    assert [(chat.id, chat.name) for chat in chats(payload)] == expected


def test_a_chat_without_a_name_shows_its_id() -> None:
    assert Chat(id=42).name == "42"
