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
OPEN_ENDED = 8 * 60
"""Minutes from which a range stops naming a time to be somewhere and only means the day."""

LINK = re.compile(r'(?i)<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>', re.S)
BLOCK_END = re.compile(r"(?i)<br\s*/?>|</(?:p|li|div|h[1-6]|ul|ol|tr|td|th|blockquote)>")
TAG = re.compile(r"<[^>]+>")
INLINE_IMAGE = re.compile(r"(?i)image\d+\.(?:png|gif|jpe?g)")


class Source(Protocol):
    """The reads a digest needs. `Hub` is the live one, a test brings its own."""

    def select(self, pupil: Pupil) -> None: ...
    def news(self) -> list[NewsItem]: ...
    def learnlog(self) -> list[LearnlogEntry]: ...
    def calendar(self, start: date, end: date) -> list[CalendarEvent]: ...
    def event_files(self, event: CalendarEvent) -> list[Attachment]: ...
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
    posts = source.news()
    items = [
        *_todo(source, today, days),
        *_calendar(source, today, days_ahead, days, _posted(posts)),
        *_news(posts, source.learnlog()),
    ]
    return PupilDigest(pupil=pupil, items=items)


def unseen(digest: PupilDigest, keys: set[str]) -> PupilDigest:
    items = [item for item in digest.items if item.key not in keys]
    return PupilDigest(pupil=digest.pupil, items=items)


def sample(digest: PupilDigest) -> PupilDigest:
    """One fact per section: shaped like a real digest, short enough to read.

    A fact that carries an attachment wins its section, so a test send also
    shows whether photos and documents arrive.
    """
    chosen: dict[Section, Item] = {}
    for item in digest.items:
        held = chosen.get(item.section)
        if held is None or (item.files and not held.files):
            chosen[item.section] = item
    return PupilDigest(pupil=digest.pupil, items=list(chosen.values()))


def headline(digest: PupilDigest, today: date) -> str:
    """The first line, which is all a phone notification shows.

    The child comes first: one message is about one child, and the name is what
    the reader looks for.
    """
    count = _plural(len(digest.items), "nytt", "nya")
    return f"{digest.pupil.first_name} · {label(today)} · {count}"


def render(digest: PupilDigest) -> str:
    """One child as plain text: the sections in read order, the facts under them.

    A fact that carries text gets a blank line above it, so its lines are not
    read as part of the fact before. A list of bare titles stays tight.
    """
    lines: list[str] = []
    for section in Section:
        chosen = [item for item in digest.items if item.section is section]
        if not chosen:
            continue
        if lines:
            lines.append("")
        lines.append(f"{section.value}:")
        for index, item in enumerate(chosen):
            if index and (item.body or chosen[index - 1].body):
                lines.append("")
            lines.append(f"• {item.title}")
            lines.extend(f"  {line}" for line in item.body.splitlines())
    return "\n".join(lines)


def _news(posts: list[NewsItem], entries: list[LearnlogEntry]) -> list[Item]:
    items = [
        Item(
            key=f"news:{post.id}",
            section=Section.NEWS,
            title=_dated(post.title, post.published_date),
            body=_body(post.content, _named(_real(post.attachments))),
            files=_real(post.attachments),
        )
        for post in posts
    ]
    items += [
        Item(
            key=f"learnlog:{entry.id}:{entry.last_modified_on}",
            section=Section.NEWS,
            title=f"Lärlogg: {entry.title}"
            + (f" ({entry.group_name})" if entry.group_name else ""),
            body=_body(
                entry.text,
                "\n".join(filter(None, (_photos(entry.media), _named(_real(entry.attachments))))),
            ),
            files=_real(entry.attachments) + entry.media[:PHOTO_LIMIT],
        )
        for entry in entries
    ]
    return items


def _calendar(
    source: Source, today: date, days_ahead: int, days: list[Day], posted: set[str]
) -> list[Item]:
    """Events and closed days in one date order, so the section reads as a timeline.

    An event the news already carries is left out: the post carries the whole
    message, and the same words twice read as two things. An entry that brings
    nothing but a letter the news brought too is the same letter, however
    differently the two were titled.
    """
    events = source.calendar(today, today + timedelta(days=days_ahead))
    dated: list[tuple[date, Item]] = []
    for event in events:
        if _plain(event.title) in posted:
            continue
        files = _real(source.event_files(event))
        if files and all(_plain(file.filename) in posted for file in files):
            continue
        dated.append((event.start_date, _event(event, files, today)))
    dated += [(day.date, _closed_day(day)) for day in days if day.closed]
    return [item for _, item in sorted(dated, key=lambda pair: pair[0])]


def _posted(posts: list[NewsItem]) -> set[str]:
    """What the news section already shows: the titles it prints and the files it sends.

    A school that publishes a letter as news and as a calendar entry both gives
    the two their own titles and hangs its own copy of the file on each, so the
    file name catches the pair the titles miss.
    """
    return {_plain(post.title) for post in posts} | {
        _plain(file.filename) for post in posts for file in _real(post.attachments)
    }


def _event(event: CalendarEvent, files: list[Attachment], today: date) -> Item:
    """An entry and whatever hangs on it: a letter is its file, not its title.

    An entry whose day has come and that carries a file has no date left to
    plan for: it is something to read, so it reads with the news, and the
    clock the calendar hung on it means nothing. An entry still ahead keeps
    its place in the timeline whether or not it brings a file with it.

    The date stays in the title either way, so the section moves where a fact
    is read and never whether it is reported.
    """
    letter = bool(files) and event.start_date <= today
    return Item(
        key=f"event:{event.id}:{event.start_date}",
        section=Section.NEWS if letter else Section.CALENDAR,
        title=f"{label(event.start_date)}: {event.title}"
        + ("" if letter else _hours(event.start_time, event.end_time)),
        body=_body(event.text, _named(files)),
        files=files,
    )


def _closed_day(day: Day) -> Item:
    return Item(
        key=f"closed:{day.date}",
        section=Section.CALENDAR,
        title=f"{label(day.date)}: stängt"
        + (f" — {day.closed_reason}" if day.closed_reason else ""),
    )


def _todo(source: Source, today: date, days: list[Day]) -> list[Item]:
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
        year, week, _ = today.isocalendar()
        items.append(
            Item(
                key=f"meeting:{year}w{week}",
                section=Section.TODO,
                title=f"{_plural(slots, 'mötestid', 'mötestider')} att boka",
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


def _plural(count: int, one: str, many: str) -> str:
    """`1 bild`, `3 bilder`: the count with the word Swedish puts after it."""
    return f"{count} {one if count == 1 else many}"


def _dated(title: str, published: str) -> str:
    """The date the Hub keeps as text, read the same way as every other date."""
    if not published:
        return title
    try:
        shown = label(date.fromisoformat(published))
    except ValueError:
        shown = published
    return f"{title} ({shown})"


def _plain(title: str) -> str:
    """One spelling of a title, so two modules that name the same thing compare equal."""
    return " ".join(title.split()).casefold()


def _hours(start: str | None, end: str | None) -> str:
    """When to be there. A range covering most of a day names no such time, so it goes.

    A calendar is drawn by dragging, and a box drawn over an afternoon and the
    evening after it says only that the day is the day.
    """
    if not start:
        return ""
    if not end:
        return f" {start}"
    span = _span(start, end)
    return "" if span is not None and span >= OPEN_ENDED else f" {start}-{end}"


def _span(start: str, end: str) -> int | None:
    """The minutes between two clocks, or nothing when either is not one.

    A clock the Hub writes some other way leaves the range as it was written:
    unread is not the same as long.
    """
    try:
        return _minutes(end) - _minutes(start)
    except ValueError:
        return None


def _minutes(clock: str) -> int:
    """`13:45` as minutes into its day."""
    hours, _, rest = clock.partition(":")
    return int(hours) * 60 + int(rest)


def _body(html: str, extra: str = "") -> str:
    """The stored text, shortened, with the extra lines kept whole below it."""
    text = html_to_text(html)
    if len(text) > BODY_LIMIT:
        text = text[:BODY_LIMIT].rstrip() + " […]"
    return "\n".join(filter(None, (text, extra)))


def _real(attachments: list[Attachment]) -> list[Attachment]:
    """Without what a mail editor pastes: `image001.png` is a signature, not a file."""
    return [item for item in attachments if not INLINE_IMAGE.fullmatch(item.filename)]


def _named(attachments: list[Attachment]) -> str:
    """Many posts hold their real content in a PDF, and the file follows the digest."""
    return "\n".join(f"Bilaga: {item.filename}" for item in attachments)


def _photos(media: list[Attachment]) -> str:
    count = len(media)
    if not count:
        return ""
    if count > PHOTO_LIMIT:
        return f"{PHOTO_LIMIT} av {_plural(count, 'bild', 'bilder')}"
    return _plural(count, "bild", "bilder")


def html_to_text(value: str) -> str:
    """Flatten the Hub's stored HTML into readable lines, keeping where a link goes."""
    without_breaks = BLOCK_END.sub("\n", LINK.sub(_link, value))
    without_tags = TAG.sub("", without_breaks)
    lines = [line.strip() for line in unescape(without_tags).splitlines()]
    return "\n".join(line for line in lines if line)


def _link(match: re.Match[str]) -> str:
    """A link without its address leaves the reader nowhere to go."""
    href = match.group(1).strip()
    text = " ".join(TAG.sub("", match.group(2)).split())
    if not text or not href or text == href or href.endswith(text):
        return text or href
    return f"{text} ({href})"
