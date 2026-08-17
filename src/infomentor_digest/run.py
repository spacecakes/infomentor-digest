"""One digest run: log in, read every child, offer what is new to every channel."""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum

from .api import Attachment, File, Hub
from .config import Settings
from .digest import PupilDigest, collect, headline, render, sample, unseen
from .notify import Channel, channels, ensure_delivered, offer
from .portal import login
from .state import Store


class Scope(StrEnum):
    """How much of what InfoMentor holds one run reports."""

    NEW = "new"
    SAMPLE = "sample"

    @property
    def remembers(self) -> bool:
        """A test send must leave the facts unreported, so the real digest still brings them."""
        return self is Scope.NEW


def run(settings: Settings, today: date, *, scope: Scope = Scope.NEW, dry_run: bool = False) -> str:
    """Return the text that was reported, empty when there was nothing new.

    Every channel keeps its own reported keys, so a channel that failed is
    offered the same facts again on the next run while the others stay quiet.
    A digest no channel took is a failed run, raised once the store holds what
    did land.
    """
    store = Store.load(settings.state_file)
    targets: list[Channel] = [] if dry_run else channels(settings)

    with login(settings) as session:
        hub = Hub(page=session.page)
        facts = [collect(hub, pupil, today, settings.days_ahead) for pupil in hub.pupils()]
        if dry_run:
            return render(
                [_take(digest, store.keys_anywhere(digest.pupil.id), scope) for digest in facts]
            )

        plans = [(channel, _plan(store, channel.name, facts, scope)) for channel in targets]
        downloads = _download(hub, [plan for _, plan in plans])

    accepted: list[bool] = []
    reported = ""
    for channel, plan in plans:
        text = render(plan)
        if not text:
            continue
        took = offer(channel, headline(plan, today), text, _files(plan, downloads))
        accepted.append(took)
        if not took:
            continue
        if scope.remembers:
            for digest in plan:
                store.add(channel.name, digest.pupil.id, digest.keys)
        reported = text

    store.save()
    ensure_delivered(accepted)
    return reported


def outcome(text: str) -> str:
    """The line a finished run leaves in the log."""
    return text or "nothing new"


def _plan(store: Store, channel: str, facts: list[PupilDigest], scope: Scope) -> list[PupilDigest]:
    """What this channel reports. A child it never reported is seeded instead."""
    plan: list[PupilDigest] = []
    for digest in facts:
        if scope is Scope.NEW and not store.knows(channel, digest.pupil.id):
            store.add(channel, digest.pupil.id, digest.keys)
            print(f"{channel}: seeded {digest.pupil.first_name} with {len(digest.keys)} facts")
            continue
        plan.append(_take(digest, store.keys(channel, digest.pupil.id), scope))
    return plan


def _take(digest: PupilDigest, reported: set[str], scope: Scope) -> PupilDigest:
    """The facts of one child this scope reports."""
    return sample(digest) if scope is Scope.SAMPLE else unseen(digest, reported)


def _download(hub: Hub, plans: Iterable[list[PupilDigest]]) -> dict[str, File]:
    """The files of the planned facts, keyed by path so two channels share one download.

    A link would ask the reader to log in, so the bytes travel with the digest.
    """
    wanted = {attachment.path: attachment for plan in plans for attachment in _attachments(plan)}
    return {path: file for path, attachment in wanted.items() if (file := hub.fetch(attachment))}


def _files(plan: list[PupilDigest], downloads: dict[str, File]) -> list[File]:
    """One file per path: a letter that reaches both children travels once."""
    paths = dict.fromkeys(attachment.path for attachment in _attachments(plan))
    return [downloads[path] for path in paths if path in downloads]


def _attachments(plan: list[PupilDigest]) -> list[Attachment]:
    return [attachment for digest in plan for item in digest.items for attachment in item.files]
