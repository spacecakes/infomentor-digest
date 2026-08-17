"""The schedule replaces a cron entry, so one process runs unattended."""

from dataclasses import dataclass, field
from datetime import datetime, time

import pytest

from infomentor_digest.config import Settings
from infomentor_digest.schedule import ADVICE, SCHOOL_TIME, attempt, next_run, parse_times

TIMES = [time(7), time(18, 30)]
FAILED = "InfoMentor digest failed"
WORKS = "InfoMentor digest works again"


def clock_at(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2025, 8, day, hour, minute, tzinfo=SCHOOL_TIME)


@dataclass
class Notices:
    """The notices the schedule sent, or a channel that takes none of them."""

    sent: list[tuple[str, str]] = field(default_factory=list)
    refuses: bool = False

    @property
    def subjects(self) -> list[str]:
        return [subject for subject, _ in self.sent]

    def send(self, _settings: Settings, subject: str, body: str) -> None:
        if self.refuses:
            raise RuntimeError("channel down")
        self.sent.append((subject, body))


@pytest.fixture(autouse=True)
def notices(monkeypatch: pytest.MonkeyPatch) -> Notices:
    """Keep every notice instead of delivering it."""
    recorder = Notices()
    monkeypatch.setattr("infomentor_digest.schedule.send", recorder.send)
    return recorder


def use_run(monkeypatch: pytest.MonkeyPatch, error: str = "") -> None:
    """Answer the schedule with a quiet run, or with one that fails."""

    def once(*args: object, **kwargs: object) -> str:
        if error:
            raise RuntimeError(error)
        return ""

    monkeypatch.setattr("infomentor_digest.schedule.run", once)


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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    notices: Notices,
    settings: Settings,
) -> None:
    """A day with nothing new says so in the log, and writes to nobody."""
    use_run(monkeypatch)

    attempt(settings)

    assert "nothing new" in capsys.readouterr().out
    assert notices.sent == []


def test_attempt_survives_a_failed_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    notices: Notices,
    settings: Settings,
) -> None:
    """A night InfoMentor is down must not end the schedule, and must not stay quiet."""
    use_run(monkeypatch, error="login timed out")

    attempt(settings)

    assert "login timed out" in capsys.readouterr().err
    assert notices.subjects == [FAILED]
    assert "login timed out" in notices.sent[0][1]
    assert ADVICE in notices.sent[0][1]


def test_the_same_failure_is_sent_once(
    monkeypatch: pytest.MonkeyPatch, notices: Notices, settings: Settings
) -> None:
    """A broken password every evening is one message. A new problem is a new message."""
    use_run(monkeypatch, error="Inloggning misslyckades")
    attempt(settings)
    attempt(settings)

    assert notices.subjects == [FAILED]

    use_run(monkeypatch, error="503 from hub.infomentor.se")
    attempt(settings)

    assert notices.subjects == [FAILED, FAILED]
    assert "503" in notices.sent[1][1]


def test_a_run_that_works_again_says_so(
    monkeypatch: pytest.MonkeyPatch, notices: Notices, settings: Settings
) -> None:
    """Silence after a failure would leave the reader guessing whether it is fixed."""
    use_run(monkeypatch, error="login timed out")
    attempt(settings)

    use_run(monkeypatch)
    attempt(settings)
    attempt(settings)

    assert notices.subjects == [FAILED, WORKS]


def test_a_notice_nobody_took_is_offered_again(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    notices: Notices,
    settings: Settings,
) -> None:
    """A Telegram outage on the failing night must not swallow the warning for good."""
    notices.refuses = True
    use_run(monkeypatch, error="login timed out")
    attempt(settings)

    printed = capsys.readouterr().err
    assert "login timed out" in printed
    assert "notice failed" in printed

    notices.refuses = False
    attempt(settings)

    assert notices.subjects == [FAILED]
