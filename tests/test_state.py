import json
from pathlib import Path

from infomentor_digest.state import Store


def test_a_missing_file_knows_no_pupil(tmp_path: Path) -> None:
    store = Store.load(tmp_path / "reported.json")

    assert store.knows("telegram", 1) is False
    assert store.keys("telegram", 1) == set()
    assert store.keys_anywhere(1) == set()


def test_saved_keys_come_back_on_the_next_run(tmp_path: Path) -> None:
    path = tmp_path / "state" / "reported.json"
    store = Store.load(path)
    store.add("telegram", 1, {"news:2", "news:1"})
    store.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "channels": {"telegram": {"1": ["news:1", "news:2"]}},
        "failure": "",
    }

    later = Store.load(path)

    assert later.knows("telegram", 1) is True
    assert later.keys("telegram", 1) == {"news:1", "news:2"}


def test_add_keeps_the_earlier_keys(tmp_path: Path) -> None:
    store = Store.load(tmp_path / "reported.json")
    store.add("telegram", 1, {"news:1"})
    store.add("telegram", 1, {"news:2"})

    assert store.keys("telegram", 1) == {"news:1", "news:2"}


def test_each_pupil_has_its_own_history(tmp_path: Path) -> None:
    store = Store.load(tmp_path / "reported.json")
    store.add("telegram", 1, {"news:1"})

    assert store.keys("telegram", 2) == set()
    assert store.knows("telegram", 2) is False


def test_each_channel_has_its_own_history(tmp_path: Path) -> None:
    """A fact the mail relay refused stays new for the mail relay only."""
    store = Store.load(tmp_path / "reported.json")
    store.add("telegram", 1, {"news:1"})

    assert store.keys("mail", 1) == set()
    assert store.knows("mail", 1) is False, "a new channel seeds instead of sending the term"
    assert store.keys_anywhere(1) == {"news:1"}


def test_a_seeded_pupil_is_known_although_it_reported_nothing(tmp_path: Path) -> None:
    store = Store.load(tmp_path / "reported.json")
    store.add("telegram", 1, set())

    assert store.knows("telegram", 1) is True


def test_a_failure_is_new_once(tmp_path: Path) -> None:
    """The reader hears about a problem once, and about a new problem again."""
    store = Store.load(tmp_path / "reported.json")

    assert store.failed("login timed out") is True
    assert store.failed("login timed out") is False
    assert store.failed("503 from the hub") is True


def test_a_failure_outlives_the_run_that_wrote_it(tmp_path: Path) -> None:
    """A restart every evening would otherwise send the same problem every evening."""
    path = tmp_path / "reported.json"
    store = Store.load(path)
    store.failed("login timed out")
    store.save()

    later = Store.load(path)

    assert later.failed("login timed out") is False
    assert later.fixed() is True
    assert later.fixed() is False, "a working run says so once"
