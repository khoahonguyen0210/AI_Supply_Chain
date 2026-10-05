"""README screenshots of the running app (Playwright on installed Edge or Chrome).

uv run --with playwright python scripts/screenshots.py --password <demo password>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

QUESTION = "Demand for wireless earbuds is expected to rise by 20%. What should I do?"
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
    page.get_by_role("navigation", name="Primary").wait_for(timeout=30_000)  # signed in


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
        if "landing" in args.pages:  # the sign-in page, before signing in
            page.goto(args.url)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)  # entrance animations
            page.screenshot(path=str(args.out / "landing.png"))
            print(f"wrote {args.out / 'landing.png'}")
        sign_in(page, args.url, args.password)
        for name in [n for n in args.pages if n != "landing"]:
            page.goto(args.url + PAGES[name])
            page.wait_for_load_state("networkidle")
            if name == "copilot":  # show a finished task, not an empty form
                page.get_by_label("Your question").fill(QUESTION)
                page.locator("form button[type=submit]").click()
                page.get_by_text("Awaiting approval", exact=False).first.wait_for(timeout=120_000)
            page.wait_for_timeout(1500)  # charts and panels finish loading
            page.screenshot(path=str(args.out / f"{name}.png"))
            print(f"wrote {args.out / f'{name}.png'}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
