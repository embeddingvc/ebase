"""
Playwright exploration tests for LinkedIn automation.

These tests are organised in three tiers:

  Tier 0 – Smoke tests (no LinkedIn account needed)
    • Playwright installs correctly and can open a browser.
    • The stealth script doesn't raise JS errors.
    • linkedin.com loads and serves the expected page title.

  Tier 1 – CDP attach tests (requires Chrome running with --remote-debugging-port)
    • Attach to the browser without launching a new one.
    • Browser stays alive after the test process exits.
    • Session (login state) is preserved from the existing Chrome window.

  Tier 2 – Human behaviour (requires attached Chrome + logged-in session)
    • Scrolls the feed with realistic dwell times.
    • Likes ~30 % of posts naturally.

Login is always done manually by the user:
    1. Run `make browser`  — opens Chrome with --remote-debugging-port=9222
    2. Log in to LinkedIn in that window
    3. Run these tests — the session is picked up automatically

Run smoke tests (offline, no Chrome needed):
    uv run tests/test_playwright_exploration.py

Run with Chrome already open (auto-detected on localhost:9222):
    uv run tests/test_playwright_exploration.py

Run against a different CDP port:
    CDP_URL=http://localhost:9223 uv run tests/test_playwright_exploration.py

Run full integration suite (also set a target profile URL):
    LINKEDIN_TARGET_URL=https://www.linkedin.com/in/<slug>/ \\
        uv run tests/test_playwright_exploration.py

Enable write-path tests (connection requests, messages, etc.):
    LINKEDIN_TARGET_URL=... RUN_WRITE_TESTS=1 \\
        uv run tests/test_playwright_exploration.py
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import urllib.request
from pathlib import Path

# Make the project root importable.
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from outreach.browser import LinkedInBrowser  # noqa: E402

# ── Config from environment ───────────────────────────────────────────────────

CDP_URL  = os.environ.get("CDP_URL", "http://localhost:9222")
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"


def _chrome_running(cdp_url: str = CDP_URL) -> bool:
    """Return True if Chrome is already listening on the CDP port."""
    try:
        urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1)
        return True
    except Exception:
        return False


HAS_CDP = _chrome_running()

# ── Result tracking ───────────────────────────────────────────────────────────

RESULTS: list[tuple[str, bool, str]] = []   # (test_name, passed, note)


def record(name: str, passed: bool, note: str = "") -> None:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}" + (f"  [{note}]" if note else ""))
    RESULTS.append((name, passed, note))


def skip(name: str, reason: str) -> None:
    print(f"  ⏭  SKIP  {name}  [{reason}]")
    RESULTS.append((name, True, f"SKIPPED: {reason}"))


# ═════════════════════════════════════════════════════════════════════════════
# Tier 0 — Smoke tests
# ═════════════════════════════════════════════════════════════════════════════

async def test_playwright_installs() -> None:
    """Verify Playwright and Chromium are installed and a browser can launch."""
    name = "playwright_installs"
    try:
        async with LinkedInBrowser(mode="launch", headless=True) as li:
            assert li.page is not None, "Page object is None"
        record(name, True)
    except Exception as exc:
        record(name, False, str(exc))


async def test_linkedin_loads() -> None:
    """Fetch linkedin.com and assert we get a recognisable title."""
    name = "linkedin_loads"
    try:
        async with LinkedInBrowser(mode="launch", headless=True) as li:
            await li.page.goto("https://www.linkedin.com", timeout=30_000)
            title = await li.page.title()
            assert "LinkedIn" in title, f"Unexpected title: {title!r}"
            record(name, True, f"title={title!r}")
    except Exception as exc:
        record(name, False, str(exc))


async def test_stealth_script() -> None:
    """Confirm the stealth overrides don't throw JS errors."""
    name = "stealth_script"
    try:
        async with LinkedInBrowser(mode="launch", headless=True) as li:
            await li.page.goto("https://www.linkedin.com", timeout=30_000)
            webdriver_flag = await li.page.evaluate("navigator.webdriver")
            assert webdriver_flag is None or webdriver_flag is False, (
                f"navigator.webdriver still exposed: {webdriver_flag!r}"
            )
            plugins_len = await li.page.evaluate("navigator.plugins.length")
            assert plugins_len > 0, "navigator.plugins is empty — stealth may have failed"
            record(name, True, f"webdriver={webdriver_flag}, plugins={plugins_len}")
    except Exception as exc:
        record(name, False, str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# Tier 1 — CDP attach tests
# ═════════════════════════════════════════════════════════════════════════════

async def test_cdp_attach() -> None:
    """
    Attach to the running Chrome and verify it stays alive after detach.

    Run `make browser` first, then log in to LinkedIn manually in that window.
    """
    name = "cdp_attach"
    if not HAS_CDP:
        skip(name, "Chrome not running — start with: make browser")
        return
    try:
        async with LinkedInBrowser(mode="attach", cdp_url=CDP_URL) as li:
            title       = await li.page.title()
            current_url = li.page.url
            print(f"    attached_to : {current_url!r}")
            print(f"    page_title  : {title!r}")

        # Re-attach after exit — proves the browser is still alive.
        async with LinkedInBrowser(mode="attach", cdp_url=CDP_URL) as li2:
            assert _chrome_running(), "Chrome no longer reachable after detach"
            _ = li2.page.url   # just confirm the page object works

        record(name, True, "browser still alive after detach")
    except Exception as exc:
        record(name, False, str(exc))


async def test_cdp_session_persistence() -> None:
    """
    Verify that the attached Chrome session is already logged in to LinkedIn.
    If this fails, log in manually in the Chrome window and re-run.
    """
    name = "cdp_session_persistence"
    if not HAS_CDP:
        skip(name, "Chrome not running — start with: make browser")
        return
    try:
        async with LinkedInBrowser(mode="attach", cdp_url=CDP_URL) as li:
            logged_in = await li.is_logged_in()
            record(
                name,
                logged_in,
                "session active" if logged_in else
                "not logged in — log in manually in the Chrome window first",
            )
    except Exception as exc:
        record(name, False, str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# Tier 2 — Human behaviour
# ═════════════════════════════════════════════════════════════════════════════

async def test_human_behavior() -> None:
    """
    Human-behaviour simulation against the LinkedIn feed.

    Single-pass mode (default):
      - Navigates to the feed and scrolls through several posts with realistic
        dwell times (8–20 s each).
      - Moves the mouse naturally between actions.
      - Likes ~30 % of posts by finding the Like button inside each visible
        post card and clicking it with a human-like motion.

    Forever mode (FOREVER=1):
      - Calls browse_forever(), which loops indefinitely with 2–6 minute
        idle breaks between rounds.  Press Ctrl-C to stop cleanly.

    This test never sends messages or connection requests.
    """
    name    = "human_behavior"
    forever = os.environ.get("FOREVER", "").lower() in ("1", "true", "yes")

    if not HAS_CDP:
        skip(name, "Chrome not running — start with: make browser")
        return
    try:
        from outreach.browser import _human_mouse_move, _human_scroll, _human_pause, _human_click

        async with LinkedInBrowser(mode="attach", cdp_url=CDP_URL) as li:
            await li.assert_logged_in()

            react_urls = [u for u in [os.environ.get("LINKEDIN_POST_URL", "")] if u]

            if forever:
                print("  [human_behavior] Running forever — Ctrl-C to stop.\n")
                await li.browse_forever(react_urls=react_urls, reaction="Like")
                record(name, True, "session ended by user")
                return

            # ── Single-pass ───────────────────────────────────────────────────

            await li.page.goto("https://www.linkedin.com/feed/", timeout=30_000)
            await _human_pause(2.0, 4.0)

            posts_to_skim = random.randint(4, 7)
            liked = 0

            for i in range(posts_to_skim):
                # Scroll down more aggressively — enough to move past the whole
                # previous post and bring the next one into view.
                for _ in range(random.randint(4, 7)):
                    await _human_scroll(li.page, "down", ticks=random.randint(120, 250))
                    await asyncio.sleep(random.uniform(0.3, 0.9))

                await _human_mouse_move(li.page)

                dwell = random.uniform(8, 20)
                print(f"    reading post {i + 1}/{posts_to_skim}  ({dwell:.0f}s)…", end="", flush=True)
                await asyncio.sleep(dwell)

                # 30 % chance: Like this post.
                # We look for Like buttons that are currently visible in the
                # viewport so we click the one the user would actually see,
                # not one buried off-screen.
                if random.random() < 0.30:
                    # Collect all Like buttons on the page and pick the last
                    # visible one (most likely to belong to the current post).
                    like_btns = li.page.locator('button[aria-label*="Reaction button"]')
                    count = await like_btns.count()
                    clicked = False
                    # Walk from the last button backwards — it's the one
                    # closest to the bottom of the current scroll position.
                    for idx in range(count - 1, -1, -1):
                        btn = like_btns.nth(idx)
                        box = await btn.bounding_box()
                        if box and box["y"] > 0:   # visible in viewport
                            await _human_click(li.page, btn)
                            await asyncio.sleep(random.uniform(0.8, 1.8))
                            liked += 1
                            clicked = True
                            print(f"  → Liked ✓")
                            break
                    if not clicked:
                        print(f"  → (no visible Like btn, skipped)")
                else:
                    print()

            await _human_scroll(li.page, "up", ticks=300)
            print(f"    ✓ feed browsed: {posts_to_skim} posts read, {liked} liked")

            screenshot_path = await li.screenshot("human_behavior")
            record(name, True, f"posts={posts_to_skim} liked={liked} screenshot={screenshot_path.name}")
    except Exception as exc:
        record(name, False, str(exc))


# ═════════════════════════════════════════════════════════════════════════════
# Runner
# ═════════════════════════════════════════════════════════════════════════════

async def main() -> int:
    print("=" * 60)
    print("Playwright Exploration Tests")
    print(f"Chrome on {CDP_URL}: {'detected ✅' if HAS_CDP else 'not running ⏭'}")
    print("=" * 60)

    print("\n── Tier 0: Smoke tests ──")
    await test_playwright_installs()
    await test_linkedin_loads()
    await test_stealth_script()

    print("\n── Tier 1: CDP attach tests ──")
    await test_cdp_attach()
    await test_cdp_session_persistence()

    print("\n── Tier 2: Human behaviour ──")
    await test_human_behavior()

    # Summary
    total   = len(RESULTS)
    skipped = sum(1 for _, _, note in RESULTS if note.startswith("SKIPPED"))
    passed  = sum(1 for _, ok, note in RESULTS if ok and not note.startswith("SKIPPED"))
    failed  = sum(1 for _, ok, _ in RESULTS if not ok)

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed / {failed} failed / {skipped} skipped  (total {total})")
    print()
    if not HAS_CDP:
        print("  → Run `make browser`, log in to LinkedIn, then re-run the tests.")
    print("=" * 60)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
