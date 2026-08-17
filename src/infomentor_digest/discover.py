"""One-shot reconnaissance: log in and write down what the account can reach.

Run this once per account to learn which portal it lands on and which sections
exist. The scraper is written against the output.
"""

import json
from pathlib import Path

from .config import Settings
from .portal import login


def discover(settings: Settings, out_dir: Path) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)

    with login(settings) as session:
        page = session.page
        page.screenshot(path=str(out_dir / "landing.png"), full_page=True)
        (out_dir / "landing.html").write_text(page.content(), encoding="utf-8")

        report: dict[str, object] = {
            "landing_url": session.landing_url,
            "on_hub": session.on_hub,
            "title": page.title(),
            "links": sorted(
                {
                    f"{(link.inner_text() or '').strip()} -> {link.get_attribute('href')}"
                    for link in page.get_by_role("link").all()
                    if link.get_attribute("href")
                }
            ),
        }

    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report
