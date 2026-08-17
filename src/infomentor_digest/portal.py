"""Log in to InfoMentor and hand back an authenticated page.

InfoMentor runs two portals. The legacy one (IM1) serves the login form at
LOGIN_URL; most schools now land on the Hub after that form is submitted.
`login` follows whichever redirect the account gets and reports where it ended.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright

from .config import Settings

LOGIN_URL = "https://infomentor.se/swedish/production/mentor/"
HUB_HOST = "hub.infomentor.se"


class LoginFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class Session:
    page: Page
    landing_url: str

    @property
    def on_hub(self) -> bool:
        return HUB_HOST in self.landing_url


@contextmanager
def login(settings: Settings) -> Generator[Session]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not settings.headed)
        page = browser.new_page(locale="sv-SE")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        page.get_by_role("textbox", name="Användarnamn").fill(settings.infomentor_username)
        page.get_by_role("textbox", name="Lösenord").fill(settings.infomentor_password)
        page.get_by_role("button", name="Logga in", exact=True).click()

        page.wait_for_load_state("networkidle")
        if LOGIN_URL in page.url:
            shown = page.locator(".error-message:visible").all_inner_texts()
            raise LoginFailed(f"{refusal(shown)} (as {settings.infomentor_username})")

        try:
            yield Session(page=page, landing_url=page.url)
        finally:
            browser.close()


def refusal(messages: Sequence[str]) -> str:
    """Why the login page came back, in InfoMentor's own words.

    The form holds one message per reason and hides the ones that do not apply,
    so only the shown text says anything.
    """
    said = " ".join(text.strip() for text in messages if text.strip())
    return said or "still on the login page"
