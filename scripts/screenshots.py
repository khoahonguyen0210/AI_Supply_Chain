"""Screenshots of the running app for the README (docs/images/).

    bash scripts/stack.sh up
    uv run --with playwright python scripts/screenshots.py --password <demo password>

Uses the installed Microsoft Edge or Chrome through Playwright (`--channel`), so no browser download
is needed. Playwright is not a project dependency; `uv run --with` brings it for this run only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

QUESTION = "Demand for SKU-001 is expected to rise by 20%. What should I do?"
PAGES = {
    "dashboard": "/",
    "workspace": "/workspace",
    "copilot": "/copilot",
    "approvals": "/approvals",
}


def sign_in(page: Page, url: str, password: str) -> None:
    page.goto(url)
    page.get_by_label("User id").fill("planner")
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--password", required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/images"))
    parser.add_argument("--channel", default="msedge", help="msedge or chrome")
    parser.add_argument("--pages", nargs="*", default=list(PAGES))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        sign_in(page, args.url, args.password)
        for name in args.pages:
            page.goto(args.url + PAGES[name])
            page.wait_for_load_state("networkidle")
            if name == "copilot":  # show a finished task, not an empty form
                page.get_by_label("Your request").fill(QUESTION)
                page.locator("form button[type=submit]").click()
                page.get_by_text("Awaiting approval", exact=False).first.wait_for(timeout=120_000)
            page.wait_for_timeout(1500)  # charts and panels finish loading
            page.screenshot(path=str(args.out / f"{name}.png"))
            print(f"wrote {args.out / f'{name}.png'}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
