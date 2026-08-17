"""The schedule replaces a cron entry, so one process runs unattended."""

from datetime import datetime, time

import pytest

from infomentor_digest.config import Settings
from infomentor_digest.schedule import SCHOOL_TIME, attempt, next_run, parse_times

TIMES = [time(7), time(18, 30)]


def clock_at(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2025, 8, day, hour, minute, tzinfo=SCHOOL_TIME)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("18:30", [time(18, 30)]),
        ("07:00,18:30", TIMES),
        ("18:30, 7:00", TIMES),
        ("18:30,18:30", [time(18, 30)]),
    ],
)
def test_parse_times_reads_the_configured_value(value: str, expected: list[time]) -> None:
    """A list is sorted and deduplicated, so the order in the file does not matter."""
    assert parse_times(value) == expected


@pytest.mark.parametrize("value", ["", "noon", "24:00", "18.30", "18:30:00", "6"])
def test_parse_times_refuses_a_value_it_cannot_run(value: str) -> None:
    with pytest.raises(ValueError, match="RUN_AT"):
        parse_times(value)


@pytest.mark.parametrize(
    ("clock", "expected"),
    [
        (clock_at(6), clock_at(7)),
        (clock_at(7), clock_at(18, 30)),
        (clock_at(12), clock_at(18, 30)),
        (clock_at(19), clock_at(7, day=18)),
        (clock_at(23, 59), clock_at(7, day=18)),
    ],
)
def test_next_run_takes_the_next_time_of_day(clock: datetime, expected: datetime) -> None:
    """A time already reached is skipped, so a run cannot repeat itself in a tight loop."""
    assert next_run(clock, TIMES) == expected


def test_attempt_reports_a_quiet_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    monkeypatch.setattr("infomentor_digest.schedule.run", lambda *args, **kwargs: "")

    attempt(settings)

    assert "nothing new" in capsys.readouterr().out


def test_attempt_survives_a_failed_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], settings: Settings
) -> None:
    """A night InfoMentor is down must not end the schedule."""

    def broken(*args: object, **kwargs: object) -> str:
        raise RuntimeError("login timed out")

    monkeypatch.setattr("infomentor_digest.schedule.run", broken)

    attempt(settings)

    assert "login timed out" in capsys.readouterr().err
