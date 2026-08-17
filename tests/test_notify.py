from dataclasses import dataclass, field
from typing import Any, Self

import pytest

from infomentor_digest import notify as notify_module
from infomentor_digest.api import File
from infomentor_digest.config import Settings
from infomentor_digest.notify import PHOTO_BYTES, send, split

TELEGRAM = {"telegram_bot_token": "token", "telegram_chat_id": "42"}
MAIL = {"smtp_host": "relay", "mail_to": "me@example.com"}


def configured(**channels: str) -> Settings:
    return Settings(infomentor_username="user", infomentor_password="secret", **channels)


def refuse(*_: object, **__: object) -> None:
    raise RuntimeError("channel down")


@dataclass
class Call:
    url: str
    data: dict[str, Any]
    files: dict[str, tuple[str, bytes, str]] | None

    @property
    def method(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass
class FakeTelegram:
    calls: list[Call] = field(default_factory=list)

    def post(self, url: str, **kwargs: Any) -> "FakeTelegram":
        self.calls.append(Call(url=url, data=kwargs["data"], files=kwargs.get("files")))
        return self

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return configured(**TELEGRAM)


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> FakeTelegram:
    fake = FakeTelegram()
    monkeypatch.setattr(notify_module.httpx, "post", fake.post)
    return fake


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The messages the relay accepted."""
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int) -> None:
            self.host = host

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def send_message(self, message: Any) -> None:
            sent.append(message)

    monkeypatch.setattr(notify_module.smtplib, "SMTP", FakeSMTP)
    return sent


def test_a_short_digest_stays_in_one_part() -> None:
    assert split("Hej\nDå", 100) == ["Hej\nDå"]


def test_a_long_digest_is_cut_between_lines() -> None:
    text = "\n".join(f"rad {number}" for number in range(1, 11))

    parts = split(text, 20)

    assert parts == ["rad 1\nrad 2\nrad 3", "rad 4\nrad 5\nrad 6", "rad 7\nrad 8\nrad 9", "rad 10"]
    assert "\n".join(parts) == text, "no line is lost or moved"
    assert all(len(part) <= 20 for part in parts)


def test_a_line_longer_than_the_limit_is_cut() -> None:
    parts = split("a" * 25, 10)

    assert parts == ["a" * 10]


def test_the_digest_goes_to_the_chat_as_plain_text(
    settings: Settings, telegram: FakeTelegram
) -> None:
    send(settings, "InfoMentor 2025-08-17", "Hej")

    (call,) = telegram.calls
    assert call.method == "sendMessage"
    assert call.data == {
        "chat_id": "42",
        "text": "InfoMentor 2025-08-17\n\nHej",
        "disable_web_page_preview": True,
    }
    assert call.files is None


def test_a_photo_goes_in_the_chat_and_a_document_as_a_file(
    settings: Settings, telegram: FakeTelegram
) -> None:
    files = [File(name="bild.jpg", content=b"jpeg"), File(name="brev.pdf", content=b"%PDF")]

    send(settings, "InfoMentor", "Hej", files)

    photo, document = telegram.calls[1:]
    assert (photo.method, photo.data["caption"]) == ("sendPhoto", "bild.jpg")
    assert photo.files == {"photo": ("bild.jpg", b"jpeg", "image/jpeg")}
    assert (document.method, document.data["caption"]) == ("sendDocument", "brev.pdf")
    assert document.files == {"document": ("brev.pdf", b"%PDF", "application/pdf")}


def test_a_photo_over_the_size_limit_goes_as_a_document(
    settings: Settings, telegram: FakeTelegram
) -> None:
    """Telegram refuses a photo of that size, and a document keeps it whole."""
    send(settings, "InfoMentor", "Hej", [File(name="bild.jpg", content=b"a" * (PHOTO_BYTES + 1))])

    assert telegram.calls[1].method == "sendDocument"


def test_a_file_of_unknown_type_still_goes_out(settings: Settings, telegram: FakeTelegram) -> None:
    send(settings, "InfoMentor", "Hej", [File(name="bilaga", content=b"?")])

    assert telegram.calls[1].files == {"document": ("bilaga", b"?", "application/octet-stream")}


def test_without_a_channel_the_run_says_so() -> None:
    with pytest.raises(RuntimeError, match="no delivery channel"):
        send(configured(), "InfoMentor", "Hej")


def test_the_mail_channel_attaches_the_files(mailbox: list[Any]) -> None:
    send(configured(**MAIL), "InfoMentor", "Hej", [File(name="brev.pdf", content=b"%PDF")])

    (message,) = mailbox
    attachments = list(message.iter_attachments())
    assert [part.get_filename() for part in attachments] == ["brev.pdf"]
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_payload(decode=True) == b"%PDF"


def test_a_digest_reaches_every_configured_channel(
    telegram: FakeTelegram, mailbox: list[Any]
) -> None:
    """Both channels configured means both deliver, not one as a spare."""
    send(
        configured(**TELEGRAM, **MAIL),
        "InfoMentor",
        "Hej",
        [File(name="brev.pdf", content=b"%PDF")],
    )

    assert [call.method for call in telegram.calls] == ["sendMessage", "sendDocument"]
    assert len(mailbox) == 1


def test_a_broken_channel_does_not_silence_the_other(
    monkeypatch: pytest.MonkeyPatch, mailbox: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(notify_module.httpx, "post", refuse)

    send(configured(**TELEGRAM, **MAIL), "InfoMentor", "Hej")

    assert len(mailbox) == 1, "the mail went out although Telegram was down"
    assert "telegram: channel down" in capsys.readouterr().err


def test_a_digest_that_reached_nobody_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The facts stay unreported, so the next run offers them again."""
    monkeypatch.setattr(notify_module.httpx, "post", refuse)
    monkeypatch.setattr(notify_module.smtplib, "SMTP", refuse)

    with pytest.raises(RuntimeError, match="every channel failed"):
        send(configured(**TELEGRAM, **MAIL), "InfoMentor", "Hej")
