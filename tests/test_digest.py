from datetime import date

import pytest
from fake import FakeSource

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
from infomentor_digest.digest import (
    BODY_LIMIT,
    PHOTO_LIMIT,
    Item,
    PupilDigest,
    Section,
    collect,
    headline,
    html_to_text,
    label,
    render,
    unseen,
)

TODAY = date(2025, 8, 17)
PUPIL = Pupil(id=1, name="Andersson, Alva")


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hej</p><p>Då</p>", "Hej\nDå"),
        ("Rad ett<br />Rad två", "Rad ett\nRad två"),
        ("<ul><li>Ett</li><li>Två</li></ul>", "Ett\nTvå"),
        ("<p>&Ouml;ppet kl 8 &amp; 16</p>", "Öppet kl 8 & 16"),
        ("<p></p><p>  Hej  </p><p></p>", "Hej"),
        ("<h2>Rubrik</h2>Text", "Rubrik\nText"),
        ("<table><tr><td>Mån</td><td>Pannkaka</td></tr></table>", "Mån\nPannkaka"),
        ('<a href="https://x.se">Länk</a>', "Länk (https://x.se)"),
        ('Skriv till <a href="mailto:bim@skolan.se">bim@skolan.se</a>', "Skriv till bim@skolan.se"),
        ('<a href="https://x.se">https://x.se</a>', "https://x.se"),
        ('<a href="https://x.se"><img src="/p.png" /></a>', "https://x.se"),
        ('<a href="https://x.se">Läs <b>mer</b></a>', "Läs mer (https://x.se)"),
        ("", ""),
    ],
)
def test_html_to_text_flattens_the_stored_markup(html: str, expected: str) -> None:
    assert html_to_text(html) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 8, 18), "mån 18 aug"),
        (date(2025, 12, 24), "ons 24 dec"),
        (date(2025, 3, 2), "sön 2 mars"),
    ],
)
def test_label_names_the_day_in_swedish(value: date, expected: str) -> None:
    assert label(value) == expected


def test_unseen_drops_a_reported_fact() -> None:
    digest = PupilDigest(
        pupil=PUPIL,
        items=[
            Item(key="news:1", section=Section.NEWS, title="Gammal"),
            Item(key="news:2", section=Section.NEWS, title="Ny"),
        ],
    )

    fresh = unseen(digest, {"news:1"})

    assert [item.key for item in fresh.items] == ["news:2"]
    assert fresh.pupil is PUPIL


def test_render_orders_the_sections_by_what_needs_you_first() -> None:
    digest = PupilDigest(
        pupil=PUPIL,
        items=[
            Item(key="news:1", section=Section.NEWS, title="Veckobrev", body="Hej\nDå"),
            Item(key="event:1", section=Section.CALENDAR, title="mån 18 aug: Skolstart"),
            Item(key="times:1", section=Section.TODO, title="mån 18 aug: tider saknas"),
        ],
    )

    assert render(digest) == (
        "Att göra:\n"
        "• mån 18 aug: tider saknas\n"
        "\n"
        "Kalender:\n"
        "• mån 18 aug: Skolstart\n"
        "\n"
        "Nytt:\n"
        "• Veckobrev\n"
        "  Hej\n"
        "  Då"
    )


def test_render_spaces_a_fact_that_carries_text() -> None:
    """Bare titles stay tight; a fact with lines under it needs air around it."""
    digest = PupilDigest(
        pupil=PUPIL,
        items=[
            Item(key="times:1", section=Section.TODO, title="mån 18 aug: tider saknas"),
            Item(key="times:2", section=Section.TODO, title="tis 19 aug: tider saknas"),
            Item(key="tasks:1:0", section=Section.TODO, title="Uppgifter", body="Läsläxa"),
            Item(key="conference:8:New", section=Section.TODO, title="Utvecklingssamtal"),
        ],
    )

    assert render(digest) == (
        "Att göra:\n"
        "• mån 18 aug: tider saknas\n"
        "• tis 19 aug: tider saknas\n"
        "\n"
        "• Uppgifter\n"
        "  Läsläxa\n"
        "\n"
        "• Utvecklingssamtal"
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "Alva · sön 17 aug · 1 nytt"), (3, "Alva · sön 17 aug · 3 nya")],
)
def test_headline_names_the_child_first_and_counts_its_facts(count: int, expected: str) -> None:
    items = [
        Item(key=f"news:{number}", section=Section.NEWS, title="Veckobrev")
        for number in range(count)
    ]

    assert headline(PupilDigest(pupil=PUPIL, items=items), TODAY) == expected


def test_render_is_empty_when_the_child_has_nothing() -> None:
    assert render(PupilDigest(pupil=PUPIL, items=[])) == ""


def test_collect_selects_the_pupil_and_asks_for_the_wanted_window() -> None:
    source = FakeSource()

    collect(source, PUPIL, TODAY, days_ahead=21)

    assert source.selected == [PUPIL.id]
    assert source.ranges == [(TODAY, date(2025, 9, 7))]


def test_collect_reports_every_module_the_pupil_has() -> None:
    source = FakeSource(
        news_items=[
            NewsItem.model_validate(
                {
                    "id": 1,
                    "title": "Veckobrev",
                    "content": "<p>Se bilagan</p>",
                    "publishedDateString": "2025-08-15",
                    "attachments": [{"title": "brev.pdf", "url": "/Resources/Resource/Download/9"}],
                }
            )
        ],
        learnlog_entries=[
            LearnlogEntry.model_validate(
                {
                    "id": 5,
                    "title": "Vi målade",
                    "text": "<p>Roligt</p>",
                    "groupName": "Solrosen",
                    "lastModifiedOn": "2025-08-16T10:00:00",
                    "media": [
                        {"fileName": "a", "fileExtension": "jpg", "fileUrl": "/a"},
                        {"fileName": "b", "fileExtension": "jpg", "fileUrl": "/b"},
                    ],
                }
            )
        ],
        events=[
            CalendarEvent.model_validate(
                {
                    "id": 3,
                    "title": "Skolfoto",
                    "startDate": "2025-08-24",
                    "startTime": "09:00",
                    "endTime": "15:00",
                }
            )
        ],
        registration_days=[
            Day.model_validate({"date": "2025-08-18", "canEdit": True}),
            Day.model_validate(
                {"date": "2025-08-20", "isSchoolClosed": True, "schoolClosedReason": "APT"}
            ),
        ],
        current_conference=Conference(id=8, status="New", last_changes="Ändrat av Bim"),
        slots=2,
        task_summary=TaskSummary.model_validate({"totalDue": 1, "totalOverdue": 0}),
        task_items=[Task.model_validate({"id": 4, "title": "Läsläxa", "dueDate": "2025-08-20"})],
    )

    digest = collect(source, PUPIL, TODAY, days_ahead=21)
    keyed = {item.key: item for item in digest.items}

    assert set(keyed) == {
        "times:2025-08-18",
        "conference:8:New",
        "meeting:2025w33",
        "tasks:1:0",
        "news:1",
        "learnlog:5:2025-08-16T10:00:00",
        "event:3:2025-08-24",
        "closed:2025-08-20",
    }
    assert keyed["times:2025-08-18"].title == "mån 18 aug: tider saknas"
    assert keyed["closed:2025-08-20"].title == "ons 20 aug: stängt — APT"
    assert keyed["meeting:2025w33"].title == "2 mötestider att boka"
    assert keyed["news:1"].title == "Veckobrev (fre 15 aug)"
    assert keyed["news:1"].body == "Se bilagan\nBilaga: brev.pdf"
    assert [item.filename for item in keyed["news:1"].files] == ["brev.pdf"]
    assert keyed["learnlog:5:2025-08-16T10:00:00"].title == "Lärlogg: Vi målade (Solrosen)"
    assert keyed["learnlog:5:2025-08-16T10:00:00"].body == "Roligt\n2 bilder"
    assert [item.filename for item in keyed["learnlog:5:2025-08-16T10:00:00"].files] == [
        "a.jpg",
        "b.jpg",
    ]
    assert keyed["event:3:2025-08-24"].title == "sön 24 aug: Skolfoto 09:00-15:00"
    assert keyed["tasks:1:0"].body == "Läsläxa (2025-08-20)"


def test_collect_leaves_out_what_the_pupil_does_not_have() -> None:
    """A module the pupil lacks answers empty, and must add no line."""
    assert collect(FakeSource(), PUPIL, TODAY, days_ahead=21).items == []


def test_collect_ignores_a_past_day() -> None:
    source = FakeSource(
        registration_days=[
            Day.model_validate({"date": "2025-08-11", "canEdit": True}),
            Day.model_validate({"date": "2025-08-16", "isSchoolClosed": True}),
        ]
    )

    assert collect(source, PUPIL, TODAY, days_ahead=21).items == []


def test_collect_stays_quiet_about_a_completed_conference() -> None:
    source = FakeSource(current_conference=Conference(id=8, status="Completed"))

    assert collect(source, PUPIL, TODAY, days_ahead=21).items == []


def test_collect_makes_a_missing_day_a_fact_of_its_own() -> None:
    """Filling in one day must leave the others reported, so each day keys itself."""
    source = FakeSource(
        registration_days=[
            Day.model_validate({"date": "2025-08-18", "canEdit": True}),
            Day.model_validate({"date": "2025-08-19", "canEdit": True}),
        ]
    )

    items = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert [item.key for item in items] == ["times:2025-08-18", "times:2025-08-19"]
    assert [item.title for item in items] == [
        "mån 18 aug: tider saknas",
        "tis 19 aug: tider saknas",
    ]


def test_collect_reads_the_calendar_as_one_timeline() -> None:
    """A closed day takes its place among the events, not a list of its own below them."""
    source = FakeSource(
        events=[
            CalendarEvent.model_validate({"id": 2, "title": "Sent", "startDate": "2025-09-01"}),
            CalendarEvent.model_validate({"id": 1, "title": "Tidigt", "startDate": "2025-08-18"}),
        ],
        registration_days=[Day.model_validate({"date": "2025-08-25", "isSchoolClosed": True})],
    )

    items = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert [item.key for item in items] == [
        "event:1:2025-08-18",
        "closed:2025-08-25",
        "event:2:2025-09-01",
    ]


def test_collect_keeps_the_attachment_name_after_a_long_post_is_cut() -> None:
    source = FakeSource(
        news_items=[
            NewsItem.model_validate(
                {
                    "id": 1,
                    "title": "Långt brev",
                    "content": "<p>" + "a" * (BODY_LIMIT + 500) + "</p>",
                    "attachments": [{"title": "brev.pdf", "url": "/Resources/Resource/Download/9"}],
                }
            )
        ]
    )

    (item,) = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert item.body.endswith("Bilaga: brev.pdf")
    assert "[…]" in item.body


def test_collect_caps_a_long_burst_of_photos() -> None:
    photos = [
        {"fileName": str(number), "fileExtension": "jpg", "fileUrl": f"/{number}"}
        for number in range(PHOTO_LIMIT + 3)
    ]
    source = FakeSource(
        learnlog_entries=[
            LearnlogEntry.model_validate({"id": 5, "title": "Utflykt", "media": photos})
        ]
    )

    (item,) = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert item.body == f"{PHOTO_LIMIT} av {len(photos)} bilder"
    assert len(item.files) == PHOTO_LIMIT


def test_collect_counts_one_photo_in_the_singular() -> None:
    source = FakeSource(
        learnlog_entries=[
            LearnlogEntry.model_validate(
                {
                    "id": 5,
                    "title": "Utflykt",
                    "media": [{"fileName": "a", "fileExtension": "jpg", "fileUrl": "/a"}],
                }
            )
        ]
    )

    (item,) = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert item.body == "1 bild"


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        ("2025-08-15", "Veckobrev (fre 15 aug)"),
        ("15 augusti 2025", "Veckobrev (15 augusti 2025)"),
        ("", "Veckobrev"),
    ],
)
def test_collect_reads_the_news_date_like_every_other_date(published: str, expected: str) -> None:
    """A date the Hub words differently is shown as it came, never as empty parentheses."""
    source = FakeSource(
        news_items=[
            NewsItem.model_validate(
                {"id": 1, "title": "Veckobrev", "publishedDateString": published}
            )
        ]
    )

    (item,) = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert item.title == expected


@pytest.mark.parametrize(
    ("slots", "title"), [(1, "1 mötestid att boka"), (8, "8 mötestider att boka")]
)
def test_collect_keys_the_meeting_times_on_the_week_not_the_count(slots: int, title: str) -> None:
    """Booking one time changes the count, which must not report the same task again."""
    (item,) = collect(FakeSource(slots=slots), PUPIL, TODAY, days_ahead=21).items

    assert item.key == "meeting:2025w33"
    assert item.title == title


def test_collect_leaves_out_the_images_a_mail_editor_pastes() -> None:
    """A post written in a mail client carries its signature images as attachments."""
    source = FakeSource(
        news_items=[
            NewsItem.model_validate(
                {
                    "id": 1,
                    "title": "Veckobrev",
                    "attachments": [
                        {"title": "image001.png", "url": "/i/1"},
                        {"title": "IMAGE002.JPG", "url": "/i/2"},
                        {"title": "brev.pdf", "url": "/Resources/Resource/Download/9"},
                    ],
                }
            )
        ]
    )

    (item,) = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert [file.filename for file in item.files] == ["brev.pdf"]
    assert item.body == "Bilaga: brev.pdf"


def test_collect_leaves_out_an_event_a_news_post_already_names() -> None:
    source = FakeSource(
        news_items=[NewsItem.model_validate({"id": 1, "title": "Föräldramöte  "})],
        events=[
            CalendarEvent.model_validate(
                {"id": 3, "title": "föräldramöte", "startDate": "2025-08-24"}
            ),
            CalendarEvent.model_validate({"id": 4, "title": "Skolfoto", "startDate": "2025-08-25"}),
        ],
    )

    items = collect(source, PUPIL, TODAY, days_ahead=21).items

    assert [item.key for item in items] == ["event:4:2025-08-25", "news:1"]
