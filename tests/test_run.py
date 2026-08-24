"""The run decides what reaches the phone: a first run seeds, a later one reports."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest
from fake import FakeSource

from infomentor_digest import run as run_module
from infomentor_digest.api import Attachment, Day, File, NewsItem, Pupil
from infomentor_digest.config import Settings
from infomentor_digest.notify import Channel
from infomentor_digest.run import Scope, run
from infomentor_digest.state import Store

TODAY = date(2025, 8, 17)
ALVA = Pupil(id=1, name="Andersson, Alva")
Message = tuple[str, str, list[File]]


@dataclass
class FakeHub(FakeSource):
    children: list[Pupil] = field(default_factory=list)
    refused: set[str] = field(default_factory=set)
    fetched: list[tuple[int, str]] = field(default_factory=list)
    """Which child was selected for each download: the Hub serves a file only to its own child."""

    def pupils(self) -> list[Pupil]:
        return self.children

    def fetch(self, attachment: Attachment) -> File | None:
        self.fetched.append((self.selected[-1], attachment.path))
        if attachment.path in self.refused:
            return None
        return File(name=attachment.filename, content=b"bytes")


@dataclass
class PerChild(FakeHub):
    """A hub whose news depends on the selected child, as the real one is."""

    per_child: dict[int, list[NewsItem]] = field(default_factory=dict)

    def news(self) -> list[NewsItem]:
        return self.per_child.get(self.selected[-1], [])


@dataclass
class Recorder:
    """A channel that keeps what it was offered, or refuses it."""

    name: str
    refuses: bool = False
    refuses_child: str = ""
    """The one child this channel will not take, while it takes the others."""
    messages: list[Message] = field(default_factory=list)

    @property
    def channel(self) -> Channel:
        return Channel(name=self.name, deliver=self.deliver)

    def deliver(self, subject: str, body: str, files: Sequence[File]) -> None:
        if self.refuses or (self.refuses_child and self.refuses_child in subject):
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


def known(
    settings: Settings, pupils: Sequence[Pupil], channels: Sequence[str] = ("telegram",)
) -> None:
    """Note these children as reported before, so the run reports them instead of seeding."""
    store = Store.load(settings.state_file)
    for channel in channels:
        for pupil in pupils:
            store.add(channel, pupil.id, set())
    store.save()


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


def test_each_child_is_its_own_message(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A message about one child lets the notification name that child."""
    noah = Pupil(id=2, name="Andersson, Noah")
    use(
        monkeypatch,
        PerChild(
            children=[ALVA, noah],
            per_child={ALVA.id: [news(1, "Veckobrev")], noah.id: [news(2, "Fritidsbrev")]},
        ),
    )
    known(settings, [ALVA, noah])

    run(settings, TODAY)

    (alva_subject, alva_body, _), (noah_subject, noah_body, _) = sent
    assert alva_subject == "InfoMentor sön 17 aug · Alva 1"
    assert noah_subject == "InfoMentor sön 17 aug · Noah 1"
    assert "Veckobrev" in alva_body
    assert "Fritidsbrev" not in alva_body, "a message holds one child"
    assert "Fritidsbrev" in noah_body


def test_a_run_with_nothing_new_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")])
    use(monkeypatch, hub)
    run(settings, TODAY)

    assert run(settings, TODAY) == ""
    assert sent == []


def test_a_sample_sends_one_fact_per_section_and_remembers_none(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A test send must read like a digest without spending the news it holds."""
    use(
        monkeypatch,
        FakeHub(
            children=[ALVA],
            news_items=[news(1, "Måndagsbrev"), news(2, "Fredagsbrev", [attachment("brev.pdf")])],
            registration_days=[
                Day.model_validate({"date": "2025-08-18", "canEdit": True}),
                Day.model_validate({"date": "2025-08-19", "canEdit": True}),
            ],
        ),
    )

    text = run(settings, TODAY, scope=Scope.SAMPLE)

    ((_, body, files),) = sent
    assert body == text
    assert text.count("•") == 2, "one line under Att göra, one under Nytt"
    assert "mån 18 aug: tider saknas" in text
    assert "tis 19 aug" not in text
    assert "Fredagsbrev" in text, "the fact carrying a file wins its section"
    assert "Måndagsbrev" not in text
    assert [file.name for file in files] == ["brev.pdf"]
    assert Store.load(settings.state_file).keys("telegram", ALVA.id) == set(), (
        "the real digest must still bring these facts"
    )


def test_a_dry_run_prints_without_sending_or_remembering(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    use(monkeypatch, FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev")]))

    text = run(settings, TODAY, dry_run=True)

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
    known(settings, [ALVA])

    run(settings, TODAY)

    ((_, _, files),) = sent
    assert [file.name for file in files] == ["brev.pdf"]
    assert files[0].content == b"bytes"


def test_a_file_both_children_have_is_downloaded_once(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A school-wide letter sits under every child, and follows each child's message."""
    noah = Pupil(id=2, name="Andersson, Noah")
    hub = FakeHub(
        children=[ALVA, noah], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])]
    )
    use(monkeypatch, hub)
    known(settings, [ALVA, noah])

    run(settings, TODAY)

    assert [[file.name for file in files] for _, _, files in sent] == [["brev.pdf"], ["brev.pdf"]]
    assert hub.fetched == [(ALVA.id, "/Download/brev.pdf")]


def test_a_file_the_hub_refuses_is_left_out(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(
        children=[ALVA],
        news_items=[news(1, "Veckobrev", [attachment("borta.pdf"), attachment("brev.pdf")])],
        refused={"/Download/borta.pdf"},
    )
    use(monkeypatch, hub)
    known(settings, [ALVA])

    text = run(settings, TODAY)

    ((_, _, files),) = sent
    assert [file.name for file in files] == ["brev.pdf"]
    assert "Bilaga: borta.pdf" in text, "the digest still names it"


def test_each_childs_file_is_downloaded_with_that_child_selected(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    """A file is served only to the session that selected its child, so both must be selected."""
    noah = Pupil(id=2, name="Andersson, Noah")
    hub = PerChild(
        children=[ALVA, noah],
        per_child={
            ALVA.id: [news(1, "Veckobrev", [attachment("veckobrev.pdf")])],
            noah.id: [news(2, "Fritids veckobrev", [attachment("fritids.pdf")])],
        },
    )
    use(monkeypatch, hub)
    known(settings, [ALVA, noah])

    run(settings, TODAY)

    assert [[file.name for file in files] for _, _, files in sent] == [
        ["veckobrev.pdf"],
        ["fritids.pdf"],
    ]
    assert hub.fetched == [
        (ALVA.id, "/Download/veckobrev.pdf"),
        (noah.id, "/Download/fritids.pdf"),
    ]


def test_a_dry_run_downloads_nothing(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, sent: list[Message]
) -> None:
    hub = FakeHub(children=[ALVA], news_items=[news(1, "Veckobrev", [attachment("brev.pdf")])])
    use(monkeypatch, hub)

    run(settings, TODAY, dry_run=True)

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
    known(settings, [ALVA], ["telegram", "mail"])

    run(settings, TODAY)

    assert telegram.messages == mail.messages
    assert hub.fetched == [(ALVA.id, "/Download/brev.pdf")], "one download serves both channels"
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


def test_a_refused_child_comes_back_while_the_other_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A child is remembered on its own, so one refusal does not repeat the whole digest."""
    telegram = Recorder("telegram", refuses_child="Noah")
    use_channels(monkeypatch, telegram)
    noah = Pupil(id=2, name="Andersson, Noah")
    hub = PerChild(
        children=[ALVA, noah],
        per_child={ALVA.id: [news(1, "Veckobrev")], noah.id: [news(2, "Fritidsbrev")]},
    )
    use(monkeypatch, hub)
    known(settings, [ALVA, noah])

    run(settings, TODAY)

    store = Store.load(settings.state_file)
    assert store.keys("telegram", ALVA.id) == {"news:1"}
    assert store.keys("telegram", noah.id) == set(), "a refused child keeps its facts"

    telegram.refuses_child = ""
    text = run(settings, TODAY)

    assert "Fritidsbrev" in text
    assert "Veckobrev" not in text, "the child that arrived stays quiet"
    assert [subject for subject, _, _ in telegram.messages] == [
        "InfoMentor sön 17 aug · Alva 1",
        "InfoMentor sön 17 aug · Noah 1",
    ]


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
