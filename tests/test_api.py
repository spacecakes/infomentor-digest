"""The models read live payloads, so every case here is a shape the Hub sends."""

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest

from infomentor_digest.api import (
    Attachment,
    CalendarEvent,
    Conference,
    Day,
    Hub,
    LearnlogEntry,
    NewsItem,
    Pupil,
    TaskSummary,
)


@dataclass
class FakeResponse:
    ok: bool
    payload: bytes = b""

    def body(self) -> bytes:
        return self.payload


def hub_answering(response: FakeResponse) -> tuple[Hub, list[str]]:
    """A hub whose browser request returns `response` and records the asked URL."""
    asked: list[str] = []

    def get(url: str) -> FakeResponse:
        asked.append(url)
        return response

    page = SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(get=get)))
    return Hub(page=cast(Any, page)), asked


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Andersson, Alva", "Alva"),
        ("Andersson, Noah Karl", "Noah Karl"),
        ("Alva", "Alva"),
        ("Efternamn,", "Efternamn,"),
    ],
)
def test_first_name_reads_the_given_name(name: str, expected: str) -> None:
    assert Pupil(id=1, name=name).first_name == expected


def test_news_reads_the_hub_payload() -> None:
    item = NewsItem.model_validate(
        {
            "id": 42,
            "title": "Jullovet 2025",
            "content": "<p>Hej</p>",
            "publishedDateString": "2025-11-17",
            "publishedBy": "Bim",
            "attachments": [{"title": "brev.pdf", "url": "/Resources/Resource/Download/1"}],
            "unknownField": "ignored",
        }
    )

    assert item.id == 42
    assert item.published_date == "2025-11-17", "the string form is what the digest prints"
    assert item.attachments[0].path == "/Resources/Resource/Download/1"
    assert item.attachments[0].filename == "brev.pdf"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"title": "brev.pdf", "url": "/Resources/Resource/Download/1"}, "brev.pdf"),
        ({"fileName": "bild", "fileExtension": "jpg", "fileUrl": "/x"}, "bild.jpg"),
        ({"fileName": "bild.JPG", "fileExtension": "jpg", "fileUrl": "/x"}, "bild.JPG"),
    ],
)
def test_attachment_reads_both_payload_shapes(row: dict[str, str], expected: str) -> None:
    """News names a file one way and a Lärlogg photo another, and one model reads both."""
    attachment = Attachment.model_validate(row)

    assert attachment.filename == expected
    assert attachment.path


def test_fetch_downloads_the_file_through_the_session() -> None:
    hub, asked = hub_answering(FakeResponse(ok=True, payload=b"%PDF-1.4"))

    file = hub.fetch(Attachment.model_validate({"title": "brev.pdf", "url": "/Download/1"}))

    assert asked == ["https://hub.infomentor.se/Download/1"]
    assert file is not None
    assert (file.name, file.content) == ("brev.pdf", b"%PDF-1.4")


def test_fetch_gives_up_on_a_file_the_hub_refuses() -> None:
    hub, _ = hub_answering(FakeResponse(ok=False))

    assert hub.fetch(Attachment.model_validate({"title": "brev.pdf", "url": "/Download/1"})) is None


def test_learnlog_reads_the_hub_payload() -> None:
    entry = LearnlogEntry.model_validate(
        {
            "id": 7,
            "title": "Välkomna tillbaka",
            "text": "<div>Vi målade</div>",
            "groupName": "Solrosen",
            "lastModifiedOn": "2025-08-15T09:00:00",
            "media": [{"fileName": "bild.jpg", "fileType": "Image"}],
        }
    )

    assert entry.group_name == "Solrosen"
    assert entry.last_modified_on == "2025-08-15T09:00:00", "the key uses it to catch an edit"
    assert len(entry.media) == 1


def test_calendar_event_reads_the_hub_payload() -> None:
    event = CalendarEvent.model_validate(
        {
            "id": 3,
            "title": "Skolfoto",
            "text": "Fotografering",
            "startDate": "2025-08-24",
            "startTime": "09:00",
            "endTime": "15:00",
            "isAllDayEvent": False,
        }
    )

    assert event.start_date == date(2025, 8, 24)
    assert event.start_time == "09:00"


@pytest.mark.parametrize(
    ("row", "missing"),
    [
        ({"canEdit": True}, True),
        ({"canEdit": True, "startDateTime": "2025-08-18T08:00:00"}, False),
        ({"canEdit": True, "isSchoolClosed": True}, False),
        ({"canEdit": True, "onLeave": True}, False),
        ({"canEdit": False}, False),
    ],
)
def test_times_missing_asks_only_for_a_day_the_parent_can_fill(
    row: dict[str, object], missing: bool
) -> None:
    day = Day.model_validate({"date": "2025-08-18", **row})

    assert day.times_missing is missing


def test_day_hours_read_the_registered_times() -> None:
    day = Day.model_validate(
        {
            "date": "2025-08-18",
            "startDateTime": "2025-08-18T08:00:00",
            "endDateTime": "2025-08-18T16:30:00",
        }
    )

    assert day.hours == "08:00-16:30"


@pytest.mark.parametrize(
    ("status", "needs_parent"),
    [("Completed", False), ("HomeReady", True), ("New", True), ("", True)],
)
def test_conference_needs_the_parent_until_it_is_completed(status: str, needs_parent: bool) -> None:
    assert Conference(id=1, status=status).needs_parent is needs_parent


def test_task_summary_reads_the_counts() -> None:
    summary = TaskSummary.model_validate({"totalDue": 2, "totalOverdue": 1, "totalDone": 5})

    assert (summary.due, summary.overdue) == (2, 1)
