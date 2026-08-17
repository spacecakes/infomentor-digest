"""Ask for what the digest needs and write `.env`, so nobody fills in a file by hand."""

from collections.abc import Mapping
from getpass import getpass
from pathlib import Path

import httpx
from pydantic import BaseModel

from .notify import telegram_url

TIMEOUT = 30


class Chat(BaseModel):
    """A Telegram chat that wrote to the bot, and can therefore be written to."""

    id: int
    title: str = ""
    first_name: str = ""
    last_name: str = ""

    @property
    def name(self) -> str:
        person = " ".join(part for part in (self.first_name, self.last_name) if part)
        return self.title or person or str(self.id)


class Event(BaseModel):
    chat: Chat


class Update(BaseModel):
    """One getUpdates entry. A word to the bot is a message, joining a group is not."""

    message: Event | None = None
    channel_post: Event | None = None
    my_chat_member: Event | None = None

    @property
    def chat(self) -> Chat | None:
        events = (self.message, self.channel_post, self.my_chat_member)
        return next((event.chat for event in events if event), None)


class Updates(BaseModel):
    result: list[Update] = []


def setup(path: Path) -> None:
    """Write `.env` from what the reader answers."""
    if path.exists():
        print(f"{path} is already there, keeping it. Delete it to answer again.")
        return

    answers = {
        "INFOMENTOR_USERNAME": _ask("InfoMentor username"),
        "INFOMENTOR_PASSWORD": _secret("InfoMentor password"),
    }
    if _yes("Deliver to Telegram?", default=True):
        answers |= _telegram()
    if _yes("Deliver to a mail relay?", default=False):
        answers |= _mail()
    answers["RUN_AT"] = _ask("When to report, in Swedish time", default="18:30")

    path.write_text(env_text(answers), encoding="utf-8")
    path.chmod(0o600)  # It holds the password and the bot token.
    print(f"\nwrote {path}")
    print("The first run records what is there and stays quiet.")
    print("The first digest comes with the first change.")


def env_text(answers: Mapping[str, str]) -> str:
    """The `.env` text. An unanswered setting is left out, so its default holds."""
    lines = ["# Written by ./setup.sh. Every setting is listed in env.example."]
    lines += [f"{key}={value}" for key, value in answers.items() if value]
    return "\n".join(lines) + "\n"


def chats(payload: object) -> list[Chat]:
    """Every chat that wrote to the bot, the most recent first, without repeats."""
    updates = Updates.model_validate(payload).result
    found = {chat.id: chat for update in reversed(updates) if (chat := update.chat)}
    return list(found.values())


def read_chats(token: str) -> list[Chat]:
    response = httpx.get(telegram_url(token, "getUpdates"), timeout=TIMEOUT)
    response.raise_for_status()
    return chats(response.json())


def _telegram() -> dict[str, str]:
    token = _ask("Bot token from @BotFather")
    if not token:
        return {}
    return {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": _chat_id(token)}


def _chat_id(token: str) -> str:
    """A bot cannot open a chat, so the reader writes first and the bot then sees them."""
    print("Write any word to your bot now. For a group, add the bot and send /start there.")
    input("Press Enter when you have: ")

    found = read_chats(token)
    if not found:
        print("No chat has written to the bot yet.")
        return _ask("Chat id")

    for number, chat in enumerate(found, start=1):
        print(f"  {number}. {chat.name} ({chat.id})")
    if len(found) == 1:
        return str(found[0].id)
    while True:
        answer = _ask("Which chat", default="1")
        if answer.isdigit() and 1 <= int(answer) <= len(found):
            return str(found[int(answer) - 1].id)
        print(f"Type a number between 1 and {len(found)}.")


def _mail() -> dict[str, str]:
    return {
        "SMTP_HOST": _ask("Relay host, which must take mail without a login"),
        "SMTP_PORT": _ask("Relay port", default="25"),
        "MAIL_TO": _ask("Send the digest to"),
        "MAIL_FROM": _ask("Send it from"),
    }


def _ask(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    return input(f"{question}{hint}: ").strip() or default


def _secret(question: str) -> str:
    return getpass(f"{question}: ").strip()


def _yes(question: str, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{question} [{hint}]: ").strip().lower()
    return default if not answer else answer.startswith("y")
