"""A refused login must say why, so the journal names the fix."""

import pytest

from infomentor_digest.portal import refusal

WRONG_PASSWORD = (
    "Inloggning misslyckades - vänligen kontrollera användarnamn och lösenord "
    "eller kontakta skolan."
)


@pytest.mark.parametrize(
    ("shown", "expected"),
    [
        ([WRONG_PASSWORD], WRONG_PASSWORD),
        (["\n  Ange lösenord\n"], "Ange lösenord"),
        ([WRONG_PASSWORD, "Ange lösenord"], f"{WRONG_PASSWORD} Ange lösenord"),
        ([], "still on the login page"),
        (["", "   "], "still on the login page"),
    ],
)
def test_the_reason_is_the_text_the_page_shows(shown: list[str], expected: str) -> None:
    assert refusal(shown) == expected
