"""Turn the Hub data into keyed facts, then render them as plain text.

Every fact carries a key. The key is what makes a digest quiet: a fact whose
key was reported before is dropped, so a daily run only shows what changed.
A fact that can change (a moved event, a new conference status) puts the
changing part in its key and reports again when it changes.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from html import unescape
from typing import Protocol

from .api import (
    Attachment,
    CalendarEvent,
    Conference,
    Day,
    LearnlogEntry,
    NewsItem,
    Pupil,
    Task,
    TaskSummary,
)

DAYS = ("mån", "tis", "ons", "tors", "fre", "lör", "sön")
MONTHS = (
    "jan",
    "feb",
    "mars",
    "april",
    "maj",
    "juni",
    "juli",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
)
BODY_LIMIT = 1200
PHOTO_LIMIT = 10
"""How many photos of one Lärlogg entry are sent. A longer burst floods the chat."""


class Source(Protocol):
    """The reads a digest needs. `Hub` is the live one, a test brings its own."""

    def select(self, pupil: Pupil) -> None: ...
    def news(self) -> list[NewsItem]: ...
    def learnlog(self) -> list[LearnlogEntry]: ...
    def calendar(self, start: date, end: date) -> list[CalendarEvent]: ...
    def days(self) -> list[Day]: ...
    def conference(self) -> Conference | None: ...
    def meeting_slots(self) -> int: ...
    def tasks(self) -> tuple[TaskSummary, list[Task]]: ...


class Section(StrEnum):
    """Also the read order: what you must do, then what happens, then the reading."""

    TODO = "Att göra"
    CALENDAR = "Kalender"
    NEWS = "Nytt"


@dataclass(frozen=True)
class Item:
    key: str
    section: Section
    title: str
    body: str = ""
    files: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True)
class PupilDigest:
    pupil: Pupil
    items: list[Item]

    @property
    def keys(self) -> set[str]:
        """What the store remembers once this digest is reported."""
        return {item.key for item in self.items}


def collect(source: Source, pupil: Pupil, today: date, days_ahead: int) -> PupilDigest:
    """Read every module the pupil has and return the facts worth reporting."""
    source.select(pupil)
    days = [day for day in source.days() if day.date >= today]
    items = [
        *_todo(source, days),
        *_calendar(source, today, days_ahead, days),
        *_news(source),
    ]
    return PupilDigest(pupil=pupil, items=items)


def unseen(digest: PupilDigest, keys: set[str]) -> PupilDigest:
    items = [item for item in digest.items if item.key not in keys]
    return PupilDigest(pupil=digest.pupil, items=items)


def headline(digests: list[PupilDigest], today: date) -> str:
    """The first line, which is all a phone notification shows."""
    counts = [f"{d.pupil.first_name} {len(d.items)}" for d in digests if d.items]
    return " · ".join([f"InfoMentor {label(today)}", *counts])


def render(digests: list[PupilDigest]) -> str:
    blocks: list[str] = []
    for digest in digests:
        if not digest.items:
            continue
        lines = [f"=== {digest.pupil.first_name} ==="]
        for section in Section:
            chosen = [item for item in digest.items if item.section is section]
            if not chosen:
                continue
            lines.append("")
            lines.append(f"{section.value}:")
            for item in chosen:
                lines.append(f"• {item.title}")
                if item.body:
                    lines.extend(f"  {line}" for line in item.body.splitlines())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _news(source: Source) -> list[Item]:
    items = [
        Item(
            key=f"news:{entry.id}",
            section=Section.NEWS,
            title=f"{entry.title} ({entry.published_date})",
            body=_body(entry.content, _named(entry.attachments)),
            files=entry.attachments,
        )
        for entry in source.news()
    ]
    items += [
        Item(
            key=f"learnlog:{entry.id}:{entry.last_modified_on}",
            section=Section.NEWS,
            title=f"Lärlogg: {entry.title}"
            + (f" ({entry.group_name})" if entry.group_name else ""),
            body=_body(
                entry.text,
                "\n".join(filter(None, (_photos(entry.media), _named(entry.attachments)))),
            ),
            files=entry.attachments + entry.media[:PHOTO_LIMIT],
        )
        for entry in source.learnlog()
    ]
    return items


def _calendar(source: Source, today: date, days_ahead: int, days: list[Day]) -> list[Item]:
    """Events and closed days in one date order, so the section reads as a timeline."""
    events = source.calendar(today, today + timedelta(days=days_ahead))
    dated = [(event.start_date, _event(event)) for event in events]
    dated += [(day.date, _closed_day(day)) for day in days if day.closed]
    return [item for _, item in sorted(dated, key=lambda pair: pair[0])]


def _event(event: CalendarEvent) -> Item:
    return Item(
        key=f"event:{event.id}:{event.start_date}",
        section=Section.CALENDAR,
        title=f"{label(event.start_date)}: {event.title}"
        + _hours(event.start_time, event.end_time),
        body=_body(event.text),
    )


def _closed_day(day: Day) -> Item:
    return Item(
        key=f"closed:{day.date}",
        section=Section.CALENDAR,
        title=f"{label(day.date)}: stängt"
        + (f" — {day.closed_reason}" if day.closed_reason else ""),
    )


def _todo(source: Source, days: list[Day]) -> list[Item]:
    items: list[Item] = [
        Item(
            key=f"times:{day.date}",
            section=Section.TODO,
            title=f"{label(day.date)}: tider saknas",
        )
        for day in days
        if day.times_missing
    ]

    conference = source.conference()
    if conference and conference.needs_parent:
        items.append(
            Item(
                key=f"conference:{conference.id}:{conference.status}",
                section=Section.TODO,
                title="Utvecklingssamtal väntar på dig",
                body=conference.last_changes,
            )
        )

    slots = source.meeting_slots()
    if slots:
        items.append(
            Item(
                key=f"meeting:{slots}",
                section=Section.TODO,
                title=f"{slots} mötestid(er) att boka",
            )
        )

    summary, tasks = source.tasks()
    if summary.due or summary.overdue:
        items.append(
            Item(
                key=f"tasks:{summary.due}:{summary.overdue}",
                section=Section.TODO,
                title=f"Uppgifter: {summary.due} att göra, {summary.overdue} försenade",
                body="\n".join(f"{task.title} ({task.due_date})" for task in tasks if task.title),
            )
        )
    return items


def label(value: date) -> str:
    return f"{DAYS[value.weekday()]} {value.day} {MONTHS[value.month - 1]}"


def _hours(start: str | None, end: str | None) -> str:
    if not start:
        return ""
    return f" {start}-{end}" if end else f" {start}"


def _body(html: str, extra: str = "") -> str:
    """The stored text, shortened, with the extra lines kept whole below it."""
    text = html_to_text(html)
    if len(text) > BODY_LIMIT:
        text = text[:BODY_LIMIT].rstrip() + " […]"
    return "\n".join(filter(None, (text, extra)))


def _named(attachments: list[Attachment]) -> str:
    """Many posts hold their real content in a PDF, and the file follows the digest."""
    return "\n".join(f"Bilaga: {item.filename}" for item in attachments)


def _photos(media: list[Attachment]) -> str:
    count = len(media)
    if not count:
        return ""
    if count > PHOTO_LIMIT:
        return f"{PHOTO_LIMIT} av {count} bilder"
    return "1 bild" if count == 1 else f"{count} bilder"


def html_to_text(value: str) -> str:
    """Flatten the Hub's stored HTML into readable lines."""
    without_breaks = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", value)
    without_tags = re.sub(r"<[^>]+>", "", without_breaks)
    lines = [line.strip() for line in unescape(without_tags).splitlines()]
    return "\n".join(line for line in lines if line)
