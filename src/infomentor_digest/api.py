"""Read the InfoMentor Hub JSON API through a logged-in browser context.

The Hub is a Knockout app that fetches everything over JSON, so no markup is
parsed here. The browser only supplies the session cookies.

A pupil sees only some of the modules. The Hub answers a module a pupil does
not have with an HTML shell instead of JSON, so every accessor treats a
non-JSON answer as "no data" and returns an empty result.
"""

from dataclasses import dataclass
from datetime import date

from playwright.sync_api import APIResponse, Page
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

BASE = "https://hub.infomentor.se"


class Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Pupil(Model):
    id: int
    name: str

    @property
    def first_name(self) -> str:
        """`Andersson, Alva` reads as `Alva`."""
        _, _, given = self.name.partition(",")
        return given.strip() or self.name


class Attachment(Model):
    """A file the Hub serves only to a logged-in session.

    News calls it an attachment and a Lärlogg photo is called media, but both
    are a name and a path, so one model reads both shapes.
    """

    name: str = Field("", validation_alias=AliasChoices("title", "fileName", "name"))
    path: str = Field("", validation_alias=AliasChoices("url", "fileUrl", "path"))
    extension: str = Field("", alias="fileExtension")

    @property
    def filename(self) -> str:
        """A photo carries its extension apart from its name, a document does not."""
        if not self.extension or self.name.lower().endswith(f".{self.extension.lower()}"):
            return self.name
        return f"{self.name}.{self.extension}"


class File(Model):
    """A downloaded attachment, ready to send."""

    name: str
    content: bytes


class LearnlogEntry(Model):
    id: int
    title: str = ""
    text: str = ""
    group_name: str = Field("", alias="groupName")
    last_modified_on: str = Field("", alias="lastModifiedOn")
    media: list[Attachment] = []
    attachments: list[Attachment] = []


class NewsItem(Model):
    id: int
    title: str = ""
    content: str = ""
    published_date: str = Field("", alias="publishedDateString")
    published_by: str = Field("", alias="publishedBy")
    attachments: list[Attachment] = []


class CalendarEvent(Model):
    id: int
    title: str = ""
    text: str = ""
    start_date: date = Field(alias="startDate")
    start_time: str | None = Field(None, alias="startTime")
    end_time: str | None = Field(None, alias="endTime")
    all_day: bool = Field(False, alias="isAllDayEvent")


class Day(Model):
    """One day of preschool or after-school attendance times."""

    date: date
    start: str | None = Field(None, alias="startDateTime")
    end: str | None = Field(None, alias="endDateTime")
    on_leave: bool = Field(False, alias="onLeave")
    locked: bool = Field(False, alias="isLocked")
    closed: bool = Field(False, alias="isSchoolClosed")
    closed_reason: str = Field("", alias="schoolClosedReason")
    can_edit: bool = Field(False, alias="canEdit")

    @property
    def times_missing(self) -> bool:
        return self.can_edit and not self.closed and not self.on_leave and self.start is None

    @property
    def hours(self) -> str:
        return f"{(self.start or '')[11:16]}-{(self.end or '')[11:16]}"


class Conference(Model):
    """A parent-teacher meeting (utvecklingssamtal) and its preparation form."""

    id: int
    status: str = ""
    last_changes: str = Field("", alias="lastChangesInfo")

    @property
    def needs_parent(self) -> bool:
        return self.status != "Completed"


class TaskSummary(Model):
    overdue: int = Field(0, alias="totalOverdue")
    due: int = Field(0, alias="totalDue")


class Task(Model):
    id: int = 0
    title: str = ""
    due_date: str = Field("", alias="dueDate")
    subject: str = ""


@dataclass(frozen=True)
class Hub:
    page: Page

    def pupils(self) -> list[Pupil]:
        """The children on the account, read from the page's own bootstrap data."""
        rows = self.page.evaluate(
            """() => (window.IMHome?.home?.homeData?.account?.pupils || [])
                 .map(p => ({id: Number(p.switchPupilUrl.split('/').pop()), name: p.name}))"""
        )
        return [Pupil.model_validate(row) for row in rows]

    def select(self, pupil: Pupil) -> None:
        """Choose which child the later calls describe. The choice lives in the session."""
        self._get(f"/Account/PupilSwitcher/SwitchPupil/{pupil.id}")

    def news(self) -> list[NewsItem]:
        payload = self._post(
            "/Communication/News/GetNewsList",
            {"pageSize": -1, "sortBy": "lastPublishDate___SORT_DESC"},
        )
        return [NewsItem.model_validate(row) for row in _rows(payload, "items")]

    def learnlog(self) -> list[LearnlogEntry]:
        payload = self._get("/learnlog/learnlog/appData")
        return [LearnlogEntry.model_validate(row) for row in _rows(payload, "entries")]

    def calendar(self, start: date, end: date) -> list[CalendarEvent]:
        payload = self._post(
            "/calendarv2/calendarv2/getentries",
            {"startDate": _slashed(start), "endDate": _slashed(end)},
        )
        return [CalendarEvent.model_validate(row) for row in _list(payload)]

    def days(self) -> list[Day]:
        """Attendance times for the current week."""
        payload = self._post("/TimeRegistration/TimeRegistration/GetTimeRegistrations/", {})
        return [Day.model_validate(row) for row in _rows(payload, "days")]

    def conference(self) -> Conference | None:
        payload = self._post("/Documentation/Conference/GetCurrentConference", {})
        return Conference.model_validate(payload) if isinstance(payload, dict) and payload else None

    def meeting_slots(self) -> int:
        """How many meeting times wait to be booked."""
        payload = self._post("/Home/meeting/GetPupilAvailabilities", {})
        return int(payload.get("totalCount", 0)) if isinstance(payload, dict) else 0

    def tasks(self) -> tuple[TaskSummary, list[Task]]:
        payload = self._post("/Task/Task/GetTasks", {"page": 1, "pageSize": 20})
        if not isinstance(payload, dict):
            return TaskSummary(), []
        return (
            TaskSummary.model_validate(payload),
            [Task.model_validate(row) for row in _rows(payload, "items")],
        )

    def fetch(self, attachment: Attachment) -> File | None:
        """Download a file so it can be sent. A link would ask the reader to log in.

        A nameless or empty file is no file: Telegram refuses both.
        """
        if not attachment.path or not attachment.filename:
            return None
        response = self.page.context.request.get(f"{BASE}{attachment.path}")
        if not response.ok:
            return None
        content = response.body()
        return File(name=attachment.filename, content=content) if content else None

    def _get(self, path: str) -> object:
        return _read(self.page.context.request.get(f"{BASE}{path}"))

    def _post(self, path: str, body: dict[str, object]) -> object:
        return _read(self.page.context.request.post(f"{BASE}{path}", data=body))


def _read(response: APIResponse) -> object:
    if not response.ok:
        raise RuntimeError(f"{response.status} from {response.url}")
    if "json" not in response.headers.get("content-type", ""):
        return {}
    return response.json()


def _rows(payload: object, key: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _list(payload: object) -> list[dict]:
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _slashed(value: date) -> str:
    return value.strftime("%Y/%m/%d")
