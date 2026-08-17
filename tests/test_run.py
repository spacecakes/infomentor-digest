"""The run decides what reaches the phone: a first run seeds, a later one reports."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest
from fake import FakeSource

from infomentor_digest import run as run_module
from infomentor_digest.api import Attachment, File, NewsItem, Pupil
from infomentor_digest.config import Settings
from infomentor_digest.notify import Channel
from infomentor_digest.run import run
from infomentor_digest.state import Store

TODAY = date(2025, 8, 17)
ALVA = Pupil(id=1, name="Andersson, Alva")
Message = tuple[str, str, list[File]]


@dataclass
class FakeHub(FakeSource):
    children: list[Pupil] = field(default_factory=list)
    refused: set[str] = field(default_factory=set)
    fetched: list[str] = field(default_factory=list)

    def pupils(self) -> list[Pupil]:
        return self.children

    def fetch(self, attachment: Attachment) -> File | None:
        self.fetched.append(attachment.path)
        if attachment.path in self.refused:
            return None
        return File(name=attachment.filename, content=b"bytes")


@dataclass
class Recorder:
    """A channel that keeps what it was offered, or refuses everything."""

    name: str
    refuses: bool = False
    messages: list[Message] = field(default_factory=list)

    @property
    def channel(self) -> Channel:
        return Channel(name=self.name, deliver=self.deliver)

    def deliver(self, subject: str, body: str, files: Sequence[File]) -> None:
        if self.refuses:
            raise RuntimeError("channel down")
        self.messages.append((subject, body, list(files)))


def use_channels(monkeypatch: pytest.MonkeyPatch, *recorders: Recorder) -> None:
    """Answer the run with these channels instead of the configured ones."""
    monkeypatch.setattr(
        run_module, "channels", lambda _settings: [recorder.channel for recorder in recorders]
    )


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[Message]:
    """One channel, keeping what the run offered it."""
    telegram = Recorder("telegram")
    use_channels(monkeypatch, telegram)
    return telegram.messages


def use(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    """Answer the run from `hub` instead of a browser session."""

    @contextmanager
    def login(_settings: Settings) -> Generator[SimpleNamespace]:
        yield SimpleNamespace(page=None)

    monkeypatch.setattr(run_module, "login", login)
    monkeypatch.setattr(run_module, "Hub", lambda page: hub)


def news(id: int, title: str, attachments: list[Attachment] | None = None) -> NewsItem:
    return NewsItem(id=id, title=title, attachments=attachments or [])


def attachment(name: str) -> Attachment:
    return Attachment.model_validate({"title": name, "url": f"/Download/{name}"})


def test_the_first_run_seeds_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")]))

    text = run(settings, TODAY)

    assert text == ""
    assert sent == []
    assert Store.load(settings.state_file).keys("telegram", ALVA.id) == {"news:1"}


def test_a_later_run_reports_only_the_new_fact(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")]))
    run(settings, TODAY)

    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev"), news(2, "Nytt")]))
    text = run(settings, TODAY)

    assert "Nytt" in text
    assert "Veckobrev" not in text, "already reported"
    assert sent == [("InfoMentor sön 17 aug · Alva 1", text, [])]


def test_a_run_with_nothing_new_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")])
    use(monkeypatch, hub)
    run(settings, TODAY)

    assert run(settings, TODAY) == ""
    assert sent == []


def test_force_reports_a_reported_fact(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")])
    use(monkeypatch, hub)
    run(settings, TODAY)

    text = run(settings, TODAY, force=True)

    assert "Veckobrev" in text
    assert sent == [("InfoMentor sön 17 aug · Alva 1", text, [])]


def test_a_dry_run_prints_without_sending_or_remembering(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")]))

    text = run(settings, TODAY, force=True, dry_run=True)

    assert "Veckobrev" in text
    assert sent == []
    assert not settings.state_file.exists()


def test_a_dry_run_leaves_out_what_a_channel_already_reported(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """Having no channel of its own, a dry run shows what no channel has yet."""
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal")]))
    run(settings, TODAY)
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal"), news(2, "Ny")]))
    run(settings, TODAY)

    text = run(settings, TODAY, dry_run=True)

    assert text == ""


def test_the_files_of_a_reported_fact_travel_with_the_digest(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A link would ask the reader to log in, so the bytes are sent instead."""
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])])
    use(monkeypatch, hub)

    run(settings, TODAY, force=True)

    ((_, _, files),) = sent
    assert [file.name for file in files] == ["brev.pdf"]
    assert files[0].content == b"bytes"


def test_a_file_both_children_have_travels_once(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A school-wide letter sits under every child, and is one upload all the same."""
    noah = Pupil(id=2, name="Andersson, Noah")
    hub = FakeHub(
        children=[ALVA, noah], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])]
    )
    use(monkeypatch, hub)

    run(settings, TODAY, force=True)

    ((_, _, files),) = sent
    assert [file.name for file in files] == ["brev.pdf"]
    assert hub.fetched == ["/Download/brev.pdf"]


def test_a_file_the_hub_refuses_is_left_out(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(
        children=[ALVA],
        news_items=[news(1, "Veckobrev", [attachment("borta.pdf"), attachment("brev.pdf")])],
        refused={"/Download/borta.pdf"},
    )
    use(monkeypatch, hub)

    text = run(settings, TODAY, force=True)

    ((_, _, files),) = sent
    assert [file.name for file in files] == ["brev.pdf"]
    assert "Bilaga: borta.pdf" in text, "the digest still names it"


def test_a_dry_run_downloads_nothing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])])
    use(monkeypatch, hub)

    run(settings, TODAY, force=True, dry_run=True)

    assert hub.fetched == []
    assert sent == []


def test_a_new_child_is_seeded_while_the_known_one_reports(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    noah = Pupil(id=2, name="Andersson, Noah")
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal")]))
    run(settings, TODAY)

    use(
        monkeypatch,
        FakeHub(children=[ALVA, noah], news_items=[news(1, "Gammal"), news(2, "Ny")]),
    )
    text = run(settings, TODAY)

    assert "=== Alva ===" in text
    assert "=== Noah ===" not in text, "a first sight of a child seeds instead of flooding"
    assert Store.load(settings.state_file).keys("telegram", noah.id) == {"news:1", "news:2"}


def test_every_channel_gets_the_same_digest(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    telegram, mail = Recorder("telegram"), Recorder("mail")
    use_channels(monkeypatch, telegram, mail)
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])])
    use(monkeypatch, hub)

    run(settings, TODAY, force=True)

    assert telegram.messages == mail.messages
    assert hub.fetched == ["/Download/brev.pdf"], "one download serves both channels"
    assert [file.name for _, _, files in mail.messages for file in files] == ["brev.pdf"]


def test_a_refused_digest_is_offered_again_and_only_to_that_channel(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    telegram, mail = Recorder("telegram"), Recorder("mail", refuses=True)
    use_channels(monkeypatch, telegram, mail)
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal")]))
    run(settings, TODAY)

    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal"), news(2, "Ny")]))
    run(settings, TODAY)

    assert "Ny" in telegram.messages[0][1], "the working channel reported it at once"
    assert mail.messages == []

    mail.refuses = False
    text = run(settings, TODAY)

    assert "Ny" in mail.messages[0][1], "the refused fact came back for the mail relay"
    assert "Ny" in text
    assert len(telegram.messages) == 1, "the channel that took it stays quiet"


def test_a_digest_no_channel_took_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A failed delivery must not read as `nothing new`, and must keep its facts."""
    use_channels(monkeypatch, Recorder("telegram", refuses=True))
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal")]))
    run(settings, TODAY)

    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal"), news(2, "Ny")]))
    with pytest.raises(RuntimeError, match="every channel failed"):
        run(settings, TODAY)

    assert Store.load(settings.state_file).keys("telegram", ALVA.id) == {"news:1"}


def test_a_channel_added_later_seeds_instead_of_sending_the_history(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    telegram = Recorder("telegram")
    use_channels(monkeypatch, telegram)
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Gammal"), news(2, "Äldre")]))
    run(settings, TODAY)

    mail = Recorder("mail")
    use_channels(monkeypatch, telegram, mail)
    run(settings, TODAY)

    assert mail.messages == []
    assert Store.load(settings.state_file).keys("mail", ALVA.id) == {"news:1", "news:2"}
