"""Deliver a digest to every channel that is configured: Telegram, a mail relay, or both."""

import mimetypes
import smtplib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from functools import partial

import httpx

from .api import File
from .config import Settings

TELEGRAM_LIMIT = 3900
PHOTO_BYTES = 10_000_000
"""Telegram takes a photo up to ten megabytes, and a document up to fifty."""

IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def telegram_url(token: str, method: str) -> str:
    """Where a bot call goes. Setup reads the chat id from the same API."""
    return f"https://api.telegram.org/bot{token}/{method}"


@dataclass(frozen=True)
class Channel:
    """One way out, holding its own configuration.

    The name is what the store and the log call it.
    """

    name: str
    deliver: Callable[[str, str, Sequence[File]], None]


def channels(settings: Settings) -> list[Channel]:
    """Every configured channel, in the order a digest is offered to them."""
    found = [
        Channel(name=name, deliver=partial(deliver, settings))
        for name, enabled, deliver in (
            ("telegram", settings.telegram_enabled, _telegram),
            ("mail", settings.mail_enabled, _mail),
        )
        if enabled
    ]
    if not found:
        raise RuntimeError("no delivery channel configured — set Telegram or SMTP in .env")
    return found


def offer(channel: Channel, subject: str, body: str, files: Sequence[File]) -> bool:
    """Deliver on one channel. False when it refused, with the reason in the log.

    A channel that refuses must not stop the others, and must not count as
    reported: the caller keeps its facts for the next run.
    """
    try:
        channel.deliver(subject, body, files)
    except Exception as error:
        print(f"delivery failed on {channel.name}: {error}", file=sys.stderr, flush=True)
        return False
    return True


def ensure_delivered(accepted: Sequence[bool]) -> None:
    """Fail when every channel refused: a message that reached nobody is a failed run.

    Nothing offered is not a failure — a quiet run has no channel to blame.
    """
    if accepted and not any(accepted):
        raise RuntimeError("every channel failed — see the log above")


def send(settings: Settings, subject: str, body: str, files: Sequence[File] = ()) -> None:
    """Deliver the same message on every configured channel, and fail when none took it."""
    ensure_delivered([offer(channel, subject, body, files) for channel in channels(settings)])


def split(text: str, limit: int) -> list[str]:
    """Cut a long digest into Telegram-sized parts, on line boundaries."""
    parts: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.splitlines():
        if length + len(line) + 1 > limit and current:
            parts.append("\n".join(current))
            current, length = [], 0
        current.append(line[:limit])
        length += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts


def content_type(name: str) -> str:
    guess, _ = mimetypes.guess_type(name)
    return guess or "application/octet-stream"


def _telegram(settings: Settings, subject: str, body: str, files: Sequence[File]) -> None:
    for part in split(f"{subject}\n\n{body}", TELEGRAM_LIMIT):
        _send_telegram(settings, part)
    for file in files:
        _send_telegram_file(settings, file)


def _send_telegram(settings: Settings, text: str) -> None:
    """Sent as plain text: the Swedish content carries `_` and `*`, which Markdown would eat."""
    _call(
        settings,
        "sendMessage",
        data={
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def _send_telegram_file(settings: Settings, file: File) -> None:
    """A photo goes in the chat, anything else goes as a document."""
    photo = content_type(file.name) in IMAGE_TYPES and len(file.content) <= PHOTO_BYTES
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    _call(
        settings,
        method,
        data={"chat_id": settings.telegram_chat_id, "caption": file.name},
        files={field: (file.name, file.content, content_type(file.name))},
    )


def _call(
    settings: Settings,
    method: str,
    data: dict[str, object],
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> None:
    response = httpx.post(
        telegram_url(settings.telegram_bot_token, method),
        data=data,
        files=files,
        timeout=120,
    )
    response.raise_for_status()


def _mail(settings: Settings, subject: str, body: str, files: Sequence[File]) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.mail_from or settings.mail_to
    message["To"] = settings.mail_to
    message.set_content(body)
    for file in files:
        maintype, _, subtype = content_type(file.name).partition("/")
        message.add_attachment(file.content, maintype=maintype, subtype=subtype, filename=file.name)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.send_message(message)
