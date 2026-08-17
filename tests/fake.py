"""A stand-in for the Hub that answers from lists given in the test."""

from dataclasses import dataclass, field
from datetime import date

from infomentor_digest.api import (
    CalendarEvent,
    Conference,
    Day,
    LearnlogEntry,
    NewsItem,
    Pupil,
    Task,
    TaskSummary,
)


@dataclass
class FakeSource:
    news_items: list[NewsItem] = field(default_factory=list)
    learnlog_entries: list[LearnlogEntry] = field(default_factory=list)
    events: list[CalendarEvent] = field(default_factory=list)
    registration_days: list[Day] = field(default_factory=list)
    current_conference: Conference | None = None
    slots: int = 0
    task_summary: TaskSummary = field(default_factory=TaskSummary)
    task_items: list[Task] = field(default_factory=list)
    selected: list[int] = field(default_factory=list)
    ranges: list[tuple[date, date]] = field(default_factory=list)

    def select(self, pupil: Pupil) -> None:
        self.selected.append(pupil.id)

    def news(self) -> list[NewsItem]:
        return self.news_items

    def learnlog(self) -> list[LearnlogEntry]:
        return self.learnlog_entries

    def calendar(self, start: date, end: date) -> list[CalendarEvent]:
        self.ranges.append((start, end))
        return self.events

    def days(self) -> list[Day]:
        return self.registration_days

    def conference(self) -> Conference | None:
        return self.current_conference

    def meeting_slots(self) -> int:
        return self.slots

    def tasks(self) -> tuple[TaskSummary, list[Task]]:
        return self.task_summary, self.task_items
