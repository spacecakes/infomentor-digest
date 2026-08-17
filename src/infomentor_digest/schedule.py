"""Run the digest at the configured times, so the machine needs no cron.

The clock is always Swedish: the school day and the times a parent can still
fill in are Swedish, wherever the machine stands.
"""

import sys
import time as clock_module
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .run import outcome, run

SCHOOL_TIME = ZoneInfo("Europe/Stockholm")


def now() -> datetime:
    return datetime.now(tz=SCHOOL_TIME)


def serve(settings: Settings) -> None:
    """Report at once, then at every configured time.

    The run on start is what makes a restart safe: a service that comes up at
    18:31 would otherwise skip the day. A repeat costs nothing, because a fact
    already reported is dropped.
    """
    times = parse_times(settings.run_at)
    print(f"schedule: {', '.join(moment.strftime('%H:%M') for moment in times)} Europe/Stockholm")
    while True:
        attempt(settings)
        target = next_run(now(), times)
        print(f"next run {target:%Y-%m-%d %H:%M}", flush=True)
        clock_module.sleep((target - now()).total_seconds())


def attempt(settings: Settings) -> None:
    """One run, with its failure written down instead of raised.

    A night InfoMentor is unreachable must cost one digest, not the schedule.
    """
    try:
        print(outcome(run(settings, now().date())), flush=True)
    except Exception as error:
        print(f"run failed: {error}", file=sys.stderr, flush=True)


def parse_times(value: str) -> list[time]:
    """Read `18:30` or `07:00,18:30` into the times of day to report at."""
    times = set()
    for part in value.split(","):
        try:
            times.add(datetime.strptime(part.strip(), "%H:%M").time())
        except ValueError:
            raise ValueError(
                f"RUN_AT takes times like 18:30 or 07:00,18:30, not {value!r}"
            ) from None
    return sorted(times)


def next_run(moment: datetime, times: list[time]) -> datetime:
    """The first configured time after `moment`, tomorrow once today runs out."""
    today = [datetime.combine(moment.date(), at, tzinfo=moment.tzinfo) for at in times]
    ahead = [target for target in today if target > moment]
    return ahead[0] if ahead else today[0] + timedelta(days=1)
