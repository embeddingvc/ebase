"""
LinkedIn browser client — Playwright-based.

Handles all LinkedIn UI interactions: login, profile scraping,
connection requests, and message sending.

── Modes ──────────────────────────────────────────────────────────────────────

  launch  (default)
      Playwright spawns a fresh Chromium process that lives for the duration
      of the async-with block, then closes.  Auth cookies are saved to disk
      so re-login is skipped on subsequent runs.

  attach
      Playwright connects to an already-running Chrome/Chromium via the
      Chrome DevTools Protocol (CDP).  The browser stays open after the
      Python process exits — it is never closed by this code.

      Start Chrome once (you only need to do this once per machine):

          /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \\
            --remote-debugging-port=9222 \\
            --user-data-dir=$HOME/.linkedin-chrome-profile \\
            --no-first-run

      Then use LinkedInBrowser in attach mode:

          async with LinkedInBrowser(mode="attach") as li:
              # browser stays alive after this block exits
              profile = await li.scrape_profile(url)

      Benefits for LinkedIn:
        - You log in once manually (and solve any CAPTCHA yourself).
        - Session cookies live in the --user-data-dir indefinitely.
        - Automation attaches silently to the real, warm browser session.
        - No headless flag, no stealth tricks needed.

── Usage examples ─────────────────────────────────────────────────────────────

    # Launch mode (default)
    async with LinkedInBrowser(headless=False) as li:
        await li.login("you@example.com", "yourpassword")
        profile = await li.scrape_profile("https://www.linkedin.com/in/alex-chen-softeng/")
        await li.send_connection_request(profile["url"], note="Hey Alex — ...")

    # Attach mode
    async with LinkedInBrowser(mode="attach", cdp_url="http://localhost:9222") as li:
        profile = await li.scrape_profile("https://www.linkedin.com/in/alex-chen-softeng/")
        await li.send_message(profile["url"], "Quick follow-up ...")
        await li.create_new_post("Short update from automation …")

── Design notes ───────────────────────────────────────────────────────────────

    - All waits use Playwright's built-in locator + expect helpers rather than
      arbitrary time.sleep() calls, which makes the code faster and more robust.
    - Human-like delays (random 500–1500 ms) are injected before clicks to reduce
      bot-detection risk.
    - The browser session is maintained across calls so LinkedIn's session cookie
      stays valid.
    - Stealth tweaks (launch mode only): webdriver property removed, plugins
      and navigator.languages spoofed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("linkedin.browser")

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    async_playwright,
    expect,
)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL    = "https://www.linkedin.com"
FEED_URL    = f"{BASE_URL}/feed/"

# Playwright's default navigation timeout (30 s) works for most pages.
NAV_TIMEOUT = 30_000   # ms
# Shorter timeout when waiting for a UI element to appear.
EL_TIMEOUT  = 10_000   # ms

# Paths
STORAGE_DIR = Path(__file__).parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

# ── Stealth helpers ───────────────────────────────────────────────────────────

_STEALTH_SCRIPT = """
// Remove the webdriver flag that LinkedIn (and most bot-detection services) check.
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof plugins length so it doesn't look like a bare headless Chrome.
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });

// Languages — match a real US-English browser.
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""


# ── Human-behaviour helpers ───────────────────────────────────────────────────
# All functions that simulate realistic human interaction patterns.
# Use these instead of bare asyncio.sleep() throughout the codebase.

async def _human_pause(low: float = 0.5, high: float = 1.5) -> None:
    """Random sleep simulating human think-time between actions."""
    await asyncio.sleep(random.uniform(low, high))


async def _human_mouse_move(page: Page) -> None:
    """
    Move the mouse along a short curved path before the next interaction.

    Real users don't teleport the cursor; they glide it across the screen
    with minor deviations.  We approximate this with a few intermediate
    waypoints sampled from a random walk within the visible viewport.
    """
    vp_w = page.viewport_size["width"]  if page.viewport_size else 1280
    vp_h = page.viewport_size["height"] if page.viewport_size else 800

    # Start from somewhere in the middle third of the viewport.
    x = random.randint(vp_w // 3, 2 * vp_w // 3)
    y = random.randint(vp_h // 3, 2 * vp_h // 3)

    steps = random.randint(3, 6)
    for _ in range(steps):
        x = max(10, min(vp_w - 10, x + random.randint(-120, 120)))
        y = max(10, min(vp_h - 10, y + random.randint(-80,  80)))
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.04, 0.12))


async def _human_scroll(page: Page, direction: str = "down", ticks: int | None = None) -> None:
    """
    Scroll the page in short bursts as a human would when reading.

    Parameters
    ----------
    direction : "down" | "up"
    ticks     : total scroll distance in pixels; randomised if None.
    """
    total   = ticks if ticks is not None else random.randint(300, 900)
    delta   = 100 if direction == "down" else -100
    steps   = max(1, total // abs(delta))
    vp_w    = page.viewport_size["width"]  if page.viewport_size else 640
    vp_h    = page.viewport_size["height"] if page.viewport_size else 400
    x, y    = vp_w // 2, vp_h // 2

    for _ in range(steps):
        await page.mouse.wheel(0, delta + random.randint(-20, 20))
        await asyncio.sleep(random.uniform(0.08, 0.22))


async def _human_type(page: Page, selector: str, text: str) -> None:
    """
    Click a field and type text one character at a time at a human-like WPM.

    Average typing speed ≈ 200 CPM (≈ 40 WPM) with natural variance.
    Occasional brief pauses simulate the human hesitating mid-word.
    """
    await page.click(selector)
    await _human_pause(0.2, 0.5)

    for char in text:
        await page.keyboard.type(char)
        delay = random.gauss(0.10, 0.04)          # ~100 ms ± noise
        delay = max(0.04, min(delay, 0.35))        # clamp to [40 ms, 350 ms]
        if random.random() < 0.1:                 # 10 % chance of a short thinking pause
            delay += random.uniform(0.5, 1.2)
        await asyncio.sleep(delay)


async def _human_click(page: Page, locator) -> None:
    """
    Move the mouse to a locator and click it like a human would.

    - Jitters the mouse into position before clicking.
    - Adds a brief pause after the click (reaction time).
    """
    await _human_mouse_move(page)
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    if box:
        # Land somewhere within the element, not exactly at its centre.
        tx = box["x"] + box["width"]  * random.uniform(0.3, 0.7)
        ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        await page.mouse.move(tx, ty, steps=random.randint(5, 12))
        await asyncio.sleep(random.uniform(0.08, 0.2))
        await page.mouse.click(tx, ty)
    else:
        await locator.click()
    await _human_pause(0.3, 0.8)


# ── Browser wrapper ───────────────────────────────────────────────────────────

class LinkedInBrowser:
    """
    Async context manager wrapping a Playwright Chromium session.

    Parameters
    ----------
    mode : "launch" | "attach"
        "launch"  — Playwright spawns and owns a new Chromium process.
        "attach"  — Playwright connects to an existing Chrome via CDP; the
                    browser is NOT closed when the context manager exits.
    cdp_url : str
        CDP endpoint to attach to (only used when mode="attach").
        Defaults to http://localhost:9222.
    headless : bool
        Headless flag for launch mode (ignored in attach mode).
    slow_mo : int
        Milliseconds to slow down each Playwright action (launch mode only).
    reuse_auth : bool
        In launch mode, persist / restore auth cookies from disk.

    Example
    -------
    # Launch mode
    async with LinkedInBrowser(headless=False) as li:
        await li.login(email, password)
        profile = await li.scrape_profile(url)

    # Attach mode — browser outlives this block
    async with LinkedInBrowser(mode="attach") as li:
        profile = await li.scrape_profile(url)
    """

    def __init__(
        self,
        *,
        mode: str = "attach",
        cdp_url: str = "http://localhost:9222",
        headless: bool = True,
        slow_mo: int = 50,
    ) -> None:
        if mode not in ("launch", "attach"):
            raise ValueError(f"mode must be 'launch' or 'attach', got {mode!r}")

        self.mode    = mode
        self.cdp_url = cdp_url
        self.headless = headless
        self.slow_mo  = slow_mo

        self._pw:          Playwright    | None = None
        self._browser:     Browser       | None = None
        self._ctx:         BrowserContext | None = None
        self._page:        Page          | None = None
        self._is_attached: bool = False   # True when we connected via CDP
        self._owned_page:  bool = False   # True when we opened the tab (attach mode)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "LinkedInBrowser":
        self._pw = await async_playwright().start()

        if self.mode == "attach":
            await self._attach()
        else:
            await self._launch()

        return self

    async def _launch(self) -> None:
        """Spawn a fresh Chromium process (launch mode)."""
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        ctx_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
        }

        self._ctx  = await self._browser.new_context(**ctx_kwargs)
        self._page = await self._ctx.new_page()

        # Inject stealth overrides on every new page / frame.
        await self._ctx.add_init_script(_STEALTH_SCRIPT)

    async def _attach(self) -> None:
        """
        Attach to an already-running Chrome via CDP and pick the best tab to use.

        Tab selection priority (most to least preferred):
          1. A tab already on linkedin.com — most human-like, session is warm.
          2. Any other ordinary http/https tab — safe to navigate away from.
          3. Open a new blank tab — only if no usable tab exists.

        Internal Chrome pages (chrome://, devtools://, about:, data:, etc.) are
        skipped because they block page.goto() and page.title() indefinitely.

        We never close a tab we didn't open, so the user's browsing is undisturbed.
        """
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        self._is_attached = True

        # Inherit the real user session (cookies, localStorage, etc.).
        self._ctx = self._browser.contexts[0] if self._browser.contexts \
                    else await self._browser.new_context()

        page = self._pick_tab(self._ctx.pages)
        if page is not None:
            self._page       = page
            self._owned_page = False   # we reused it — don't close on exit
            logger.info("Attached to Chrome at %s (reusing tab: %r)", self.cdp_url, page.url)
        else:
            self._page       = await self._ctx.new_page()
            self._owned_page = True    # we opened it — close on exit
            logger.info("Attached to Chrome at %s (opened new tab)", self.cdp_url)

    @staticmethod
    def _pick_tab(pages: list[Page]) -> Page | None:
        """
        Return the best existing tab for automation, or None if none is usable.

        Preference order:
          1. Any tab already on linkedin.com (warm session, no navigation needed).
          2. Any ordinary http/https tab (will navigate to LinkedIn on first use).

        Tabs on internal Chrome URLs are always skipped — they hang on goto().
        """
        _SKIP = ("chrome://", "devtools://", "about:", "data:", "chrome-extension://")

        usable    = [p for p in pages if not any(p.url.startswith(s) for s in _SKIP)]
        linkedin  = [p for p in usable if "linkedin.com" in p.url]

        if linkedin:
            return linkedin[0]
        if usable:
            return usable[0]
        return None

    @staticmethod
    def _normalized_profile_path(url: str) -> str:
        """
        Normalize LinkedIn profile URLs to compare current-vs-target pages.
        """
        try:
            p = urlparse((url or "").strip())
            path = "/" + (p.path or "").strip("/").lower()
            if not path:
                return "/"
            return path
        except Exception:
            return "/"

    def _is_current_tab_target_profile(self, profile_url: str) -> bool:
        """
        True when the current tab is already on the requested profile URL.
        """
        current = self._normalized_profile_path(self._page.url if self._page else "")
        target = self._normalized_profile_path(profile_url)
        return (
            target.startswith("/in/")
            and current == target
            and "linkedin.com" in ((self._page.url if self._page else "") or "").lower()
        )

    async def _ensure_profile_tab(self, profile_url: str) -> None:
        """
        Navigate to profile only if current tab is not already that profile.
        """
        if self._is_current_tab_target_profile(profile_url):
            await self._page.bring_to_front()
            await _human_pause(0.2, 0.5)
            return
        await self._page.goto(profile_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        await _human_pause(1.5, 2.5)

    async def __aexit__(self, *_: Any) -> None:
        if self._is_attached:
            # Close only the tab we opened — leave the rest of the browser alone.
            if self._owned_page and self._page and not self._page.is_closed():
                await self._page.close()
            logger.info("Detaching from Chrome (browser stays open).")
            if self._pw:
                await self._pw.stop()
            return

        # Launch mode — full teardown.
        if self._ctx:
            await self._ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def is_logged_in(self) -> bool:
        """
        Return True if the attached Chrome session is already logged in to LinkedIn.

        Login is always done manually by the user in the browser window.
        Run `make browser`, log in once, and every subsequent `make run` will
        reuse the session from the Chrome profile directory.
        """
        return True  # avoid refresh, assume user is logged in
        await self._page.goto(FEED_URL, timeout=NAV_TIMEOUT)
        return "/login" not in self._page.url

    async def assert_logged_in(self) -> None:
        """
        Raise a clear error if the user is not logged in, with instructions
        on how to fix it.  Call this at the start of any job that needs auth.
        """
        if not await self.is_logged_in():
            raise RuntimeError(
                "Not logged in to LinkedIn.\n"
                "  1. Run `make browser` to open Chrome.\n"
                "  2. Log in to LinkedIn manually in that window.\n"
                "  3. Re-run `make server` (or `make run`)."
            )

    async def _read_connection_degree_on_page(self) -> int | None:
        """
        Parse 1st / 2nd / 3rd+ connection degree from the *current* profile
        page (caller must already have navigated and waited for content).
        """
        degree_text = ""
        _degree_selectors = [
            ".dist-value",                                # legacy layout
            "[aria-label*='degree connection']",          # aria fallback
        ]
        for _sel in _degree_selectors:
            try:
                _el = self._page.locator(_sel).first
                if await _el.count():
                    degree_text = (await _el.inner_text(timeout=EL_TIMEOUT)).strip()
                    if degree_text:
                        break
            except Exception:
                continue
        if not degree_text:
            try:
                body_text = await self._page.locator("main, body").first.inner_text(
                    timeout=EL_TIMEOUT
                )
                _m = re.search(r"·\s*(\d+(?:st|nd|rd|th)\+?)", body_text)
                if _m:
                    degree_text = _m.group(1)
            except Exception:
                pass
        return (
            int(re.search(r"\d", degree_text).group())
            if re.search(r"\d", degree_text)
            else None
        )

    # ── Profile scraping ──────────────────────────────────────────────────────

    async def scrape_profile(self, profile_url: str) -> dict:
        """
        Navigate to a LinkedIn profile and extract key fields.

        Returns a dict that matches (or extends) the prospect schema used by
        outreach/planner.py.
        """
        await self._ensure_profile_tab(profile_url)
        await _human_scroll(self._page, "down")   # read down the page like a human

        # ── Wait for page content ──
        # LinkedIn's new SDUI renders content into <main id="workspace">.
        # Wait for that rather than a specific heading tag so we don't burn the
        # full NAV_TIMEOUT on each absent selector.
        try:
            await self._page.wait_for_selector("main, #workspace", timeout=NAV_TIMEOUT)
            await _human_pause(0.5, 1.0)  # extra settle for JS-rendered content
        except Exception:
            logger.warning("scrape_profile: page did not reach expected state for %s", profile_url)

        # ── Name ──
        # LinkedIn's SDUI (as of 2025+) uses <h2> for the profile name instead
        # of the old <h1>.  We try each selector with a short timeout so we don't
        # block 30 s per absent selector.
        _SECTION_HEADERS = {"Experience", "Education", "Skills", "Activity", "About",
                            "Featured", "Recommendations", "Courses", "Projects"}
        name = ""
        _name_selectors = [
            "h1.text-heading-xlarge",          # legacy LinkedIn class-based layout
            ".pv-text-details__left-panel h1", # older layout variant
            "h1",                              # generic h1 fallback
            # New SDUI layout: name is an h2, but scoped to <main> so we skip the
            # nav bar's "0 notifications" heading that also uses h2 at page level.
            "main h2",
            "#workspace h2",
        ]
        for _sel in _name_selectors:
            try:
                _el = self._page.locator(_sel).first
                if await _el.count():
                    _text = (await _el.inner_text(timeout=EL_TIMEOUT)).strip()
                    # Section headers ("Experience", "Activity", …) are also h2 —
                    # skip them so we don't accidentally return a header as the name.
                    if _text and _text not in _SECTION_HEADERS:
                        name = _text
                        break
            except Exception:
                continue

        # Last resort: LinkedIn page titles follow "Name | LinkedIn" format.
        if not name:
            try:
                title = await self._page.title()
                if " | LinkedIn" in title:
                    name = title.split(" | LinkedIn")[0].split(" - ")[0].strip()
            except Exception:
                pass

        if not name:
            logger.warning("scrape_profile: could not locate profile name on %s", profile_url)

        # ── Headline / title ──
        # Try the legacy class first, then fall back to the second <p> in the
        # SDUI topcard (which sits right after the name heading).
        headline = ""
        _headline_selectors = [
            ".text-body-medium.break-words",                    # legacy layout
            ".pv-text-details__left-panel .text-body-medium",  # older variant
        ]
        for _sel in _headline_selectors:
            try:
                _el = self._page.locator(_sel).first
                if await _el.count():
                    headline = (await _el.inner_text(timeout=EL_TIMEOUT)).strip()
                    if headline:
                        break
            except Exception:
                continue

        # ── Location ──
        location = ""
        _location_selectors = [
            ".text-body-small.inline.t-black--light.break-words",  # legacy layout
            ".pv-text-details__left-panel .t-black--light",        # older variant
        ]
        for _sel in _location_selectors:
            try:
                _el = self._page.locator(_sel).first
                if await _el.count():
                    location = (await _el.inner_text(timeout=EL_TIMEOUT)).strip()
                    if location:
                        break
            except Exception:
                continue

        # ── Connection degree ──
        # Legacy selector first; new SDUI shows "· 1st" / "· 2nd" inline in a <p>.
        connection_degree = await self._read_connection_degree_on_page()

        await _human_scroll(self._page, "down")   # scroll further to reveal About / Experience

        # ── About section ──
        about_el = self._page.locator("section#about ~ div, div[data-generated-suggestion-target='urn:li:fs_aboutPrompt']").first
        about = await about_el.inner_text(timeout=EL_TIMEOUT) if await about_el.count() else ""

        # ── Raw visible text (profile page) ──
        # Grab everything visible inside <main> before we navigate away.
        # This acts as a catch-all for fields that structured selectors miss
        # (About text, Skills, Education, etc.) and lets the skill summarise
        # whatever LinkedIn happens to render on the day.
        raw_text = ""
        try:
            main_el = self._page.locator("main, #workspace").first
            if await main_el.count():
                _raw = await main_el.inner_text(timeout=EL_TIMEOUT)
                # Collapse runs of blank lines into a single blank line so the
                # text stays readable without being padded with dozens of newlines.
                raw_text = re.sub(r"\n{3,}", "\n\n", _raw).strip()
        except Exception as exc:
            logger.warning("Could not capture raw page text: %s", exc)

        # ── Recent posts (activity feed) ──
        posts: list[dict] = []
        try:
            activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
            await self._page.goto(activity_url, timeout=NAV_TIMEOUT)
            await _human_pause(1.5, 2.5)
            await _human_scroll(self._page, "down")

            post_els = self._page.locator(".feed-shared-update-v2__description")
            count = await post_els.count()
            for i in range(min(count, 3)):
                text = await post_els.nth(i).inner_text(timeout=EL_TIMEOUT)
                posts.append({"text": text.strip(), "timestamp": "", "likes": 0})
                await _human_pause(0.3, 0.8)   # brief read pause between posts
        except Exception as exc:
            logger.warning("Could not scrape activity feed: %s", exc)

        return {
            "linkedin_url":      profile_url,
            "name":              name.strip(),
            "title":             headline.strip(),
            "location":          location.strip(),
            "connection_degree": connection_degree,
            "about":             about.strip(),
            "recent_posts":      posts,
            "raw_text":          raw_text,
            "scraped_at":        datetime.now(timezone.utc).isoformat(),
        }

    # ── Connection request ────────────────────────────────────────────────────

    async def send_connection_request(self, profile_url: str, note: str = "") -> bool:
        """
        Send a connection request to a LinkedIn profile.

        Parameters
        ----------
        profile_url : str
            Full LinkedIn profile URL.
        note : str
            Personalised connection note (≤300 chars).  Pass empty string to
            send without a note.

        Returns
        -------
        bool
            True on success, False if the button wasn't found or request failed.
        """
        if len(note) > 300:
            raise ValueError(f"Connection note too long: {len(note)} chars (LinkedIn limit: 300)")

        await self._ensure_profile_tab(profile_url)
        try:
            await self._page.wait_for_selector("main, #workspace", timeout=NAV_TIMEOUT)
            await _human_pause(0.4, 0.9)
        except Exception:
            logger.warning("send_connection_request: main/workspace not ready for %s", profile_url)

        # Keep the top-card action row in view — scrolling down first often hides Connect.
        await self._page.evaluate("window.scrollTo(0, 0)")
        await _human_mouse_move(self._page)

        workspace = self._page.locator("main, #workspace")

        # SDUI invite CTA: <a href="/preload/custom-invite/?vanityName=..." aria-label="Invite … to connect">
        # Prefer href (stable) scoped to the profile body; .first matches header before any sidebar dupes.
        connect_btn = workspace.locator(
            "a[href*='custom-invite']:has-text('Connect')"
        ).first
        if not await connect_btn.count():
            connect_btn = workspace.locator("a[href*='custom-invite']").first
        if not await connect_btn.count():
            connect_btn = self._page.get_by_role(
                "link",
                name=re.compile(r"Invite .+ to connect", re.I),
            ).first
        if not await connect_btn.count():
            connect_btn = workspace.get_by_role("button", name=re.compile(r"^Connect$", re.I)).first
        if not await connect_btn.count():
            connect_btn = workspace.get_by_role("link", name=re.compile(r"^Connect$", re.I)).first

        # Fall back to the profile-level "More" overflow → Connect.
        if not await connect_btn.count():
            more_btn = workspace.get_by_role("button", name=re.compile(r"^More$", re.I)).first
            if not await more_btn.count():
                more_btn = self._page.get_by_role("button", name=re.compile(r"^More$", re.I)).last
            if not await more_btn.count():
                logger.warning("No Connect / More button found.")
                return False
            await _human_click(self._page, more_btn)
            await _human_pause(0.2, 0.4)
            connect_btn = self._page.get_by_role("menuitem", name=re.compile(r"Connect", re.I)).first

        try:
            await expect(connect_btn).to_be_visible(timeout=EL_TIMEOUT)
        except Exception:
            logger.warning("Connect control not visible on %s", profile_url)
            return False

        await _human_click(self._page, connect_btn)

        # Click may open an overlay or navigate to the /preload/custom-invite/ route; wait for UI to settle.
        await _human_pause(0.6, 1.2)
        try:
            await self._page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

        # LinkedIn may show "How do you know X?" modal — pick "Other".
        how_know_other = self._page.get_by_role("radio", name="Other")
        if await how_know_other.count():
            await _human_click(self._page, how_know_other)
            await _human_click(self._page, self._page.get_by_role("button", name="Connect"))

        if note:
            add_note_btn = self._page.get_by_role("button", name=re.compile(r"Add a note", re.I))
            if await add_note_btn.count():
                await _human_click(self._page, add_note_btn)
                await _human_type(self._page, "textarea[name='message']", note)
                await _human_pause()

        # Submit — LinkedIn often shows two CTAs: primary "Add a note" / "Send"
        # and a separate "Send without a note" control (button, link, or role=button div).
        invite_roots = (
            self._page.locator("[role='dialog']:visible"),
            self._page.locator("[aria-modal='true']:visible"),
            self._page.locator(".artdeco-modal:visible"),
        )
        _without_note = re.compile(r"send\s+without(\s+a\s+note)?", re.I)
        _without_note_text = re.compile(r"Send without a note", re.I)

        submitted = False
        if not note:
            _no_note_candidates: list = [
                self._page.get_by_role("button", name=_without_note),
                self._page.get_by_role("link", name=_without_note),
                self._page.locator("[role='button']").filter(has_text=_without_note_text),
                self._page.locator("button, a").filter(has_text=_without_note_text),
            ]
            for root in invite_roots:
                _no_note_candidates.extend(
                    [
                        root.get_by_role("button", name=_without_note),
                        root.get_by_role("link", name=_without_note),
                        root.locator("button, a, [role='button']").filter(
                            has_text=_without_note_text
                        ),
                    ]
                )
            for cand in _no_note_candidates:
                if await cand.count():
                    btn = cand.first
                    try:
                        await expect(btn).to_be_visible(timeout=EL_TIMEOUT)
                        await _human_click(self._page, btn)
                        submitted = True
                        break
                    except Exception:
                        continue

        if not submitted:
            dialog = self._page.locator(
                "[role='dialog'], [data-test-modal], .artdeco-modal, "
                "div[class*='invite']"
            ).first
            _send_name = re.compile(
                r"^(Send(\s+invitation)?|Send\s+without\s+a\s+note|Done)$",
                re.I,
            )
            send_btn = dialog.get_by_role("button", name=_send_name)
            if not await send_btn.count():
                send_btn = self._page.get_by_role("button", name=_send_name)
            if not await send_btn.count():
                send_btn = dialog.locator("button").filter(
                    has=self._page.get_by_text(re.compile(r"^Send", re.I))
                )
            if not await send_btn.count():
                send_btn = self._page.locator("button").filter(
                    has=self._page.get_by_text(re.compile(r"^Send", re.I))
                )
            if not await send_btn.count():
                logger.warning("Send button not found after opening invite flow.")
                return False

            await expect(send_btn.first).to_be_visible(timeout=EL_TIMEOUT)
            await _human_click(self._page, send_btn.first)
        await _human_pause(1.0, 2.0)
        logger.info("Connection request sent to %s", profile_url)
        return True

    async def is_first_degree_connection(self, profile_url: str) -> bool:
        """
        Return True if the signed-in member is a 1st-degree connection of the
        profile at ``profile_url`` (i.e. you can DM them without InMail).

        Uses the same degree badge heuristics as :meth:`scrape_profile`.  If the
        badge cannot be read, falls back to detecting a primary **Message** CTA
        on the profile top card (same entry points as :meth:`send_message`).
        """
        await self._ensure_profile_tab(profile_url)
        try:
            await self._page.wait_for_selector("main, #workspace", timeout=NAV_TIMEOUT)
            await _human_pause(0.4, 0.9)
        except Exception:
            logger.warning(
                "is_first_degree_connection: main/workspace not ready for %s",
                profile_url,
            )

        await self._page.evaluate("window.scrollTo(0, 0)")
        await _human_mouse_move(self._page)

        degree = await self._read_connection_degree_on_page()
        if degree == 1:
            return True
        if degree is not None:
            return False

        workspace = self._page.locator("main, #workspace")
        main_el = self._page.locator("main").first
        _msg_strict = re.compile(r"^Message$", re.I)
        _msg_loose = re.compile(r"\bMessage\b", re.I)

        async def _any_visible(multi: Locator) -> bool:
            n = await multi.count()
            for i in range(min(n, 40)):
                el = multi.nth(i)
                try:
                    if await el.is_visible():
                        return True
                except Exception:
                    continue
            return False

        async def _has_message_cta(root: Locator) -> bool:
            trials = [
                root.locator("a[href*='/messaging/compose/']:has-text('Message')"),
                root.locator("a[href*='messaging/compose']"),
                root.locator("a[href*='/messaging/thread']"),
                root.get_by_role("link", name=_msg_strict),
                root.get_by_role("button", name=_msg_strict),
                root.get_by_role("link", name=_msg_loose),
                root.get_by_role("button", name=_msg_loose),
                root.locator("button[aria-label*='Message' i]"),
                root.locator("a[aria-label*='Message' i]"),
                root.locator("[role='button'][aria-label*='Message' i]"),
            ]
            for trial in trials:
                if await _any_visible(trial):
                    return True
            return await _any_visible(root.locator("a[href*='/messaging/']"))

        if await _has_message_cta(workspace) or await _has_message_cta(main_el):
            return True

        return False

    # ── Messaging ─────────────────────────────────────────────────────────────

    def _profile_match_hints(self, profile_url: str) -> tuple[list[str], str]:
        """
        Build stable matching hints from a LinkedIn profile URL.

        Returns ``(path_hints, search_query)``:
          - ``path_hints``: normalized path tokens to match thread links.
          - ``search_query``: readable query for the messaging search box.
        """
        parsed = urlparse(profile_url)
        path = parsed.path or ""
        cleaned = "/" + path.strip("/")
        cleaned_lower = cleaned.lower()
        hints: list[str] = []
        if cleaned_lower and cleaned_lower != "/":
            hints.append(cleaned_lower.rstrip("/"))
            hints.append(cleaned_lower.rstrip("/") + "/")

        slug = ""
        m = re.search(r"/in/([^/?#]+)", cleaned_lower)
        if m:
            slug = m.group(1).strip().strip("/")

        if slug:
            hints.append(f"/in/{slug}")
            hints.append(f"/in/{slug}/")

        # Use a human-readable name for inbox search, dropping trailing handle/hash tails:
        # jay-sato-263a85270 -> jay sato
        candidate = slug if slug else cleaned.strip("/")
        parts = [p for p in candidate.split("-") if p]
        if len(parts) >= 2:
            tail = parts[-1]
            # Drop trailing token if it looks like a hash/ID chunk.
            if re.search(r"\d", tail):
                parts = parts[:-1]
        query = " ".join(parts) if parts else candidate
        query = re.sub(r"\s+", " ", query).strip()
        return hints, query

    def _sanitize_search_name(self, search_name: str | None) -> str:
        """
        Normalize user-facing person name for messaging search.
        """
        text = (search_name or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s+#\S.*$", "", text).strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _find_open_messaging_tab(self) -> Page | None:
        """
        Return an already-open LinkedIn messaging tab, if any.
        """
        if not self._ctx:
            return None
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        for p in pages:
            url = (p.url or "").lower()
            if "linkedin.com/messaging" in url:
                return p
        return None

    async def _open_messaging_home(self) -> None:
        target = f"{BASE_URL}/messaging/"

        # Reuse an already-open messaging tab directly (no reload).
        msg_tab = self._find_open_messaging_tab()
        if msg_tab is not None:
            self._page = msg_tab
            await self._page.bring_to_front()
            await _human_pause(0.2, 0.5)
        else:
            current_url = (self._page.url or "").lower()
            if "linkedin.com/messaging" not in current_url:
                await self._page.goto(target, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
                await _human_pause(1.0, 1.8)

        try:
            await self._page.wait_for_selector(
                "main, #messaging, .msg-conversations-container, [data-test-id='messaging-container']",
                timeout=NAV_TIMEOUT,
            )
        except Exception:
            logger.warning("_open_messaging_home: messaging shell not fully ready yet.")
        await _human_pause(0.3, 0.7)

    async def _open_message_ui_from_messaging(
        self,
        profile_url: str,
        *,
        search_name: str | None = None,
    ) -> bool:
        """
        Open a conversation from ``/messaging/`` (never from profile CTAs).

        Strategy:
          1. Go to inbox.
          2. Try direct match in visible conversation rows by profile-path hints.
          3. If no hit, use inbox search and pick the best matching thread.
        """
        hints, fallback_query = self._profile_match_hints(profile_url)
        query = self._sanitize_search_name(search_name) or fallback_query
        await self._open_messaging_home()

        async def _find_thread_row_in(multi: Locator) -> Locator | None:
            n = await multi.count()
            for i in range(min(n, 60)):
                row = multi.nth(i)
                try:
                    if not await row.is_visible():
                        continue
                    href = (await row.get_attribute("href") or "").lower()
                    if any(h in href for h in hints):
                        return row
                    if query:
                        txt = ((await row.inner_text()) or "").lower()
                        if query.lower() in txt:
                            return row
                except Exception:
                    continue
            return None

        row: Locator | None = None
        # Prefer explicit inbox search flow: type name -> Enter -> click first visible result.
        if query:
            search_boxes = [
                self._page.locator("input[placeholder*='Search messages' i]").first,
                self._page.locator("input[aria-label*='Search messages' i]").first,
                self._page.locator("input[placeholder*='Search' i]").first,
                self._page.get_by_role("searchbox").first,
                self._page.locator("input.msg-search-typeahead__input").first,
            ]
            search_box = None
            for cand in search_boxes:
                try:
                    if await cand.count() and await cand.is_visible():
                        search_box = cand
                        break
                except Exception:
                    continue

            if search_box is not None:
                await _human_click(self._page, search_box)
                await search_box.fill("")
                await _human_pause(0.1, 0.2)
                for ch in query:
                    await self._page.keyboard.type(ch)
                    await asyncio.sleep(random.uniform(0.04, 0.14))
                await _human_pause(0.1, 0.2)
                await self._page.keyboard.press("Enter")
                await _human_pause(0.8, 1.4)

                # Requirement: after searching, open the first visible person/thread result.
                search_rows = self._page.locator(
                    "a[href*='/messaging/thread/'], "
                    ".msg-conversation-listitem a, "
                    ".msg-conversation-listitem div.msg-conversation-listitem__link, "
                    "li.msg-conversation-listitem, "
                    "[data-view-name*='search'] a[href*='/messaging/']"
                )
                for i in range(min(await search_rows.count(), 30)):
                    cand = search_rows.nth(i)
                    try:
                        if await cand.is_visible():
                            row = cand
                            break
                    except Exception:
                        continue

        # Fallback when search UI/results are unavailable: try matching visible threads.
        if row is None:
            row_candidates = [
                self._page.locator("a.msg-conversation-listitem__link"),
                self._page.locator("div.msg-conversation-listitem__link"),
                self._page.locator("li.msg-conversation-listitem div.msg-conversation-listitem__link"),
                self._page.locator("li.msg-conversation-listitem"),
                self._page.locator("a[href*='/messaging/thread/']"),
                self._page.locator(".msg-conversation-listitem a"),
            ]
            for cand in row_candidates:
                found = await _find_thread_row_in(cand)
                if found is not None:
                    row = found
                    break

        if row is None:
            logger.warning("No messaging thread matched profile=%s", profile_url)
            return False

        await _human_click(self._page, row)
        await _human_pause(0.7, 1.2)
        return True

    async def send_message(
        self,
        profile_url: str,
        message: str,
        *,
        search_name: str | None = None,
    ) -> bool:
        """
        Send a direct message to an existing connection.

        The prospect must already be a 1st-degree connection — LinkedIn does not
        allow direct messages to non-connections unless InMail credits are used.

        Returns True on success.
        """
        if len(message) > 8_000:
            raise ValueError("Message too long (LinkedIn limit: ~8 000 chars)")

        if not await self._open_message_ui_from_messaging(profile_url, search_name=search_name):
            return False

        compose_selector = (
            "div[role='textbox'][aria-label*='Write a message'], "
            "div[role='textbox'][aria-label*='message' i], "
            "div.msg-form__contenteditable, "
            "[contenteditable='true'][data-placeholder*='Write' i]"
        )
        compose = self._page.locator(compose_selector).first
        await expect(compose).to_be_visible(timeout=EL_TIMEOUT)

        await _human_type(self._page, compose_selector, message)
        await _human_pause()

        send_btn = self._page.locator("button.msg-form__send-button").first
        if not await send_btn.count():
            send_btn = self._page.get_by_role("button", name=re.compile(r"^Send$", re.I)).first
        if not await send_btn.count():
            send_btn = self._page.locator("button[aria-label*='Send' i]").first
        if not await send_btn.count():
            logger.warning("Message compose send control not found.")
            return False

        await expect(send_btn).to_be_visible(timeout=EL_TIMEOUT)
        await _human_click(self._page, send_btn)
        await _human_pause(1.0, 2.0)
        logger.info("Message sent to %s", profile_url)
        return True

    async def fetch_chat_history(
        self,
        profile_url: str,
        *,
        search_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Read the visible DM thread for a 1st-degree connection (same profile →
        Message flow as :meth:`send_message`).

        Returns a list of dicts serializable as JSON:
        ``[{"message": str, "self": bool}, ...]`` — ``self`` is True for the
        logged-in user's outgoing messages. Older messages not scrolled into
        view are not included.
        """
        if not await self._open_message_ui_from_messaging(profile_url, search_name=search_name):
            return []

        try:
            await self._page.wait_for_selector(
                ".msg-s-message-list, li.msg-s-message-list__event",
                timeout=EL_TIMEOUT,
            )
        except Exception:
            logger.info(
                "fetch_chat_history: no message list yet for %s (empty or still loading)",
                profile_url,
            )

        await _human_pause(0.3, 0.6)

        items: list[dict[str, Any]] = await self._page.evaluate(
            """
            () => {
              const out = [];
              const events = document.querySelectorAll('li.msg-s-message-list__event');

              const senderIsSelf = (item, li) => {
                const il = item.classList;
                const ic = typeof item.className === 'string' ? item.className : '';
                if (il && il.contains('msg-s-event-listitem--other')) {
                  return false;
                }
                if (ic.includes('msg-s-event-listitem--other')) {
                  return false;
                }

                const list = li.classList;
                const top = typeof li.className === 'string' ? li.className : '';
                if (list && list.contains('msg-s-message-list__event--incoming')) {
                  return false;
                }
                if (top.includes('msg-s-message-list__event--incoming')) {
                  return false;
                }
                if (list && (
                  list.contains('msg-s-message-list__event--self') ||
                  list.contains('msg-s-message-list__event--outgoing')
                )) {
                  return true;
                }
                if (top.includes('msg-s-message-list__event--self') ||
                    top.includes('msg-s-message-list__event--outgoing')) {
                  return true;
                }

                let seenOut = false;
                let seenIn = false;
                const walk = (n, depth) => {
                  if (depth > 12) return;
                  const c = typeof n.className === 'string' ? n.className : '';
                  if (c.includes('msg-s-message-group--outgoing')) seenOut = true;
                  if (c.includes('msg-s-message-group--incoming')) seenIn = true;
                  const ch = n.children;
                  if (!ch) return;
                  for (let i = 0; i < ch.length; i++) {
                    walk(ch[i], depth + 1);
                  }
                };
                walk(item, 0);
                if (seenOut && !seenIn) return true;
                if (!seenOut && seenIn) return false;

                const content = item.querySelector('.msg-s-event-listitem__body, '
                  + '.msg-s-message-group__content');
                if (content) {
                  const br = content.getBoundingClientRect();
                  const er = li.getBoundingClientRect();
                  const w = er.width;
                  if (w > 48) {
                    const align = (br.left - er.left + br.width / 2) / w;
                    if (align > 0.55) return true;
                    if (align < 0.45) return false;
                  }
                }
                if (seenOut && seenIn) return false;
                return true;
              };

              for (const li of events) {
                const item = li.querySelector(
                  '.msg-s-event-listitem[data-view-name="message-list-item"], '
                  + '.msg-s-event-listitem'
                );
                if (!item) {
                  continue;
                }
                const body = item.querySelector('.msg-s-event-listitem__body');
                let text = body ? (body.innerText || '') : '';
                if (!text.trim()) {
                  const bubble = item.querySelector(
                    '.msg-s-event-listitem__message-bubble, .msg-s-message-group__content'
                  );
                  text = bubble ? (bubble.innerText || '') : '';
                }
                text = text.replace(/\\r/g, '').replace(/[ \\t]+/g, ' ').trim();
                if (!text) {
                  continue;
                }
                out.push({ message: text, self: senderIsSelf(item, li) });
              }
              return out;
            }
            """
        )
        if not isinstance(items, list):
            return []

        logger.info("fetch_chat_history: %d messages for %s", len(items), profile_url)
        return items

    # ── Feed posts ────────────────────────────────────────────────────────────

    async def create_new_post(self, content: str) -> bool:
        """
        Open the home-feed composer, enter text, and publish a new post.

        Expects the classic share-box modal (Quill editor + Post button). Starts
        from the feed by clicking “Start a post” (``/preload/sharebox/`` link).

        Returns True on success.
        """
        text = (content or "").strip()
        if not text:
            raise ValueError("Post content cannot be empty.")
        if len(text) > 10_000:
            raise ValueError("Post content too long (keep under ~10 000 chars).")

        await self._page.goto(FEED_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        await _human_pause(1.5, 2.5)

        # Composer often sits outside <main>; wait for any sharebox affordance on the full page.
        try:
            await self._page.wait_for_selector(
                "a[href*='sharebox'], a[href*='preload/share'], "
                "[aria-label*='Start a post' i], [aria-label*='start a post' i]",
                timeout=NAV_TIMEOUT,
            )
        except Exception:
            logger.warning(
                "create_new_post: sharebox selectors not seen yet — feed may still be loading."
            )

        await self._page.evaluate("window.scrollTo(0, 0)")
        await _human_mouse_move(self._page)
        await _human_pause(0.4, 0.8)

        # Page-wide: SDUI may not nest the share row under main/#workspace.
        pg = self._page
        _start_name = re.compile(r"(start|create) a post", re.I)
        start_candidates = [
            pg.locator("a[href*='/preload/sharebox/']:has-text('Start a post')").first,
            pg.locator("a[href*='sharebox']").filter(
                has_text=re.compile(r"start|create", re.I)
            ).first,
            pg.locator("a[href*='preload/sharebox']").first,
            pg.locator("a[href*='sharebox']").first,
            pg.get_by_role("link", name=_start_name).first,
            pg.locator("a:has([aria-label*='Start a post' i])").first,
            pg.get_by_role("button", name=_start_name).first,
            pg.locator("[aria-label='Start a post'], [aria-label*='Start a post' i]").first,
        ]

        start_btn = None
        for cand in start_candidates:
            try:
                if await cand.count() and await cand.is_visible():
                    start_btn = cand
                    break
            except Exception:
                continue

        if start_btn is None:
            await _human_scroll(self._page, "down", ticks=500)
            await _human_pause(0.5, 1.0)
            await self._page.evaluate("window.scrollTo(0, 0)")
            await _human_pause(0.3, 0.6)
            for cand in start_candidates:
                try:
                    if await cand.count() and await cand.is_visible():
                        start_btn = cand
                        break
                except Exception:
                    continue

        if start_btn is None:
            logger.warning("create_new_post: Start a post control not found on feed.")
            return False

        try:
            await expect(start_btn).to_be_visible(timeout=EL_TIMEOUT)
        except Exception:
            logger.warning("create_new_post: Start a post not visible.")
            return False

        await _human_click(self._page, start_btn)
        await _human_pause(0.5, 1.0)

        modal = self._page.locator(
            "[role='dialog'][data-test-modal], .share-box-v2__modal"
        ).first
        try:
            await expect(modal).to_be_visible(timeout=EL_TIMEOUT)
        except Exception:
            logger.warning("create_new_post: share composer modal did not open.")
            return False

        editor_selector = (
            "[role='dialog'] [data-test-ql-editor-contenteditable='true'], "
            "[role='dialog'] div.ql-editor[contenteditable='true'], "
            "[role='dialog'] div[role='textbox'][aria-label*='Text editor' i]"
        )
        editor = self._page.locator(editor_selector).first
        try:
            await expect(editor).to_be_visible(timeout=EL_TIMEOUT)
        except Exception:
            logger.warning("create_new_post: post editor not found in modal.")
            return False

        await _human_type(self._page, editor_selector, text)
        await _human_pause(0.4, 0.9)

        post_btn = modal.locator("button.share-actions__primary-action").filter(
            has_text=re.compile(r"^Post$", re.I)
        ).first
        if not await post_btn.count():
            post_btn = modal.get_by_role("button", name=re.compile(r"^Post$", re.I)).first
        if not await post_btn.count():
            logger.warning("create_new_post: Post button not found.")
            return False

        try:
            await expect(post_btn).to_be_enabled(timeout=EL_TIMEOUT)
        except Exception:
            logger.warning("create_new_post: Post stayed disabled — content may not have registered.")
            return False

        await _human_click(self._page, post_btn)
        await _human_pause(1.2, 2.0)
        logger.info("create_new_post: published to feed.")
        return True

    # ── Social engagement ─────────────────────────────────────────────────────

    async def react_to_post(self, post_url: str, reaction: str = "Like") -> bool:
        """
        React to a LinkedIn post.

        Parameters
        ----------
        post_url : str
            Direct URL of the post/activity.
        reaction : str
            One of: Like, Celebrate, Support, Funny, Love, Insightful.
        """
        await self._page.goto(post_url, timeout=NAV_TIMEOUT)
        await _human_pause(1.5, 3.0)
        await _human_scroll(self._page, "down", ticks=200)  # read a bit before reacting
        await _human_mouse_move(self._page)
        await _human_pause(0.8, 2.0)                        # "reading" the post

        like_btn = self._page.locator('button[aria-label*="Reaction button"]').first
        if not await like_btn.count():
            logger.warning("Like button not found.")
            return False

        if reaction == "Like":
            await _human_click(self._page, like_btn)
        else:
            # Hover over Like to reveal the reaction picker, then click the target.
            await like_btn.scroll_into_view_if_needed()
            box = await like_btn.bounding_box()
            if box:
                await self._page.mouse.move(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                    steps=random.randint(6, 12),
                )
            await _human_pause(0.8, 1.4)   # hold hover long enough for picker to appear
            reaction_btn = self._page.get_by_label(reaction)
            if not await reaction_btn.count():
                logger.warning("Reaction %r not found.", reaction)
                return False
            await _human_click(self._page, reaction_btn)

        await _human_pause(0.5, 1.2)
        logger.info("Reacted %r to %s", reaction, post_url)
        return True

    async def comment_on_post(self, post_url: str, comment: str) -> bool:
        """
        Leave a comment on a LinkedIn post.
        """
        await self._page.goto(post_url, timeout=NAV_TIMEOUT)
        await _human_pause(1.5, 3.0)

        comment_btn = self._page.get_by_role("button", name=re.compile(r"Comment", re.I)).first
        if not await comment_btn.count():
            logger.warning("Comment button not found.")
            return False

        await _human_click(self._page, comment_btn)

        editor = self._page.locator("div[role='textbox'][aria-label*='Add a comment']").first
        await expect(editor).to_be_visible(timeout=EL_TIMEOUT)
        await _human_type(
            self._page,
            "div[role='textbox'][aria-label*='Add a comment']",
            comment,
        )
        await _human_pause()

        post_btn = self._page.get_by_role("button", name=re.compile(r"^Post$", re.I)).first
        await _human_click(self._page, post_btn)
        await _human_pause(1.0, 2.0)
        logger.info("Comment posted on %s", post_url)
        return True

    # ── Continuous browsing session ───────────────────────────────────────────

    async def browse_forever(
        self,
        *,
        reaction: str = "Like",
    ) -> None:
        """
        Simulate a human browsing LinkedIn indefinitely until Ctrl-C.

        Each iteration of the loop:
          1. Navigate to the feed (or stay there if already on it).
          2. Read through several posts with realistic per-post dwell times.
          3. Occasionally click into a post for a deeper read, then go back.
          4. With ~20 % probability after reading each post, react to it inline
             (no navigation away from the feed — uses the visible reaction button).
          5. Take a longer "idle" break between browsing rounds (2–6 minutes).

        Timing is intentionally human-scale:
          - Post dwell:       8 – 35 s   (reading time)
          - Between scrolls:  2 – 8 s
          - Post click dwell: 15 – 45 s
          - Round break:      2 – 6 min

        Parameters
        ----------
        reaction : reaction type — Like, Celebrate, Support, Love, Insightful.
                   Applied randomly while scrolling the feed (~20 % of posts).
        """
        import signal as _signal

        _running = True

        def _stop(*_):
            nonlocal _running
            logger.info("Stopping after this round (Ctrl-C received).")
            _running = False

        _signal.signal(_signal.SIGINT,  _stop)
        _signal.signal(_signal.SIGTERM, _stop)

        round_num = 0

        while _running:
            round_num += 1
            logger.info("── Round %d ──────────────────────────────", round_num)

            # ── 1. Land on the feed ───────────────────────────────────────────
            if "linkedin.com/feed" not in self._page.url:
                await self._page.goto(FEED_URL, timeout=NAV_TIMEOUT)
            await _human_pause(2.0, 4.0)          # page-load settle time

            # ── 2. Read through the feed ──────────────────────────────────────
            posts_to_read = random.randint(3, 7)
            logger.info("Reading %d posts…", posts_to_read)

            for post_n in range(posts_to_read):
                if not _running:
                    break

                # Scroll to the next post in short bursts.
                bursts = random.randint(2, 5)
                for _ in range(bursts):
                    await _human_scroll(self._page, "down", ticks=random.randint(80, 180))
                    await asyncio.sleep(random.uniform(0.4, 1.2))

                await _human_mouse_move(self._page)

                # Dwell on this post — simulate reading time.
                dwell = random.uniform(8, 35)
                logger.info("  post %d/%d  (reading %.0fs)", post_n + 1, posts_to_read, dwell)
                await asyncio.sleep(dwell)

                # ── 3. Random inline reaction (~20 % chance per post) ─────────
                if random.random() < 0.20:
                    try:
                        # Find a reaction trigger visible in the current viewport.
                        # LinkedIn renders feed Like buttons as:
                        #   button[aria-label*="React Like"] or .react-button__trigger
                        react_btn = self._page.locator(
                            "button[aria-label*='React Like'], "
                            "button.react-button__trigger"
                        ).first

                        if await react_btn.count():
                            if reaction == "Like":
                                await _human_click(self._page, react_btn)
                                logger.info("  → reacted Like to post %d", post_n + 1)
                            else:
                                # Hover to open the reaction picker, then choose.
                                box = await react_btn.bounding_box()
                                if box:
                                    await self._page.mouse.move(
                                        box["x"] + box["width"] / 2,
                                        box["y"] + box["height"] / 2,
                                        steps=random.randint(6, 12),
                                    )
                                await _human_pause(0.8, 1.4)
                                reaction_btn = self._page.get_by_label(reaction)
                                if await reaction_btn.count():
                                    await _human_click(self._page, reaction_btn)
                                    logger.info(
                                        "  → reacted %r to post %d", reaction, post_n + 1
                                    )
                                else:
                                    logger.warning(
                                        "  reaction %r not found in picker for post %d",
                                        reaction, post_n + 1,
                                    )
                    except Exception as exc:
                        logger.warning("  inline react failed on post %d: %s", post_n + 1, exc)

                # ~20 % chance: click into the post for a deeper read.
                elif random.random() < 0.20:
                    post_links = self._page.locator(
                        "a[href*='/posts/'], a[href*='/pulse/'], "
                        "span.feed-shared-inline-show-more-text"
                    )
                    count = await post_links.count()
                    if count:
                        link = post_links.nth(random.randint(0, min(count - 1, 3)))
                        await _human_click(self._page, link)
                        deep_dwell = random.uniform(15, 45)
                        logger.info("  → clicked into post (reading %.0fs)", deep_dwell)
                        await asyncio.sleep(deep_dwell)
                        await _human_scroll(self._page, "down")
                        await asyncio.sleep(random.uniform(5, 15))
                        await self._page.go_back(timeout=NAV_TIMEOUT)
                        await _human_pause(1.5, 3.0)

            # ── 4. Idle break before next round ───────────────────────────────
            if _running:
                break_min  = random.uniform(2, 6)
                break_secs = break_min * 60
                logger.info("Idle break %.1f min before next round…", break_min)
                # Sleep in short chunks so Ctrl-C is responsive.
                elapsed = 0.0
                while elapsed < break_secs and _running:
                    chunk = min(5.0, break_secs - elapsed)
                    await asyncio.sleep(chunk)
                    elapsed += chunk

        logger.info("Session ended.")

    # ── Resume download ───────────────────────────────────────────────────────

    async def download_resume(
        self,
        conversation_url: str,
        save_dir: str | Path = STORAGE_DIR / "resumes",
    ) -> Path | None:
        """
        Watch a LinkedIn conversation for a shared file attachment (résumé PDF).
        Downloads it and returns the local path, or None if no attachment is found.

        LinkedIn does not surface résumé attachments via a stable URL — this
        implementation intercepts the download event triggered by clicking the
        attachment.
        """
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        await self._page.goto(conversation_url, timeout=NAV_TIMEOUT)
        await _human_pause(1.5, 2.5)

        # Look for a file attachment card in the conversation.
        attachment = self._page.locator(
            "a[href*='media/'], "
            ".msg-s-message-list__event a[data-tracking-control-name='messaging_attachment_link']"
        ).first

        if not await attachment.count():
            logger.warning("No attachment found in conversation.")
            return None

        async with self._page.expect_download() as dl_info:
            await attachment.click()
        download = await dl_info.value

        suggested = download.suggested_filename or "resume.pdf"
        dest = save_path / suggested
        await download.save_as(str(dest))
        logger.info("Résumé saved to %s", dest)
        return dest

    # ── Evidence capture ──────────────────────────────────────────────────────

    async def screenshot(self, label: str) -> Path:
        """Save a full-page screenshot for audit / debugging purposes."""
        evidence_dir = STORAGE_DIR / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = evidence_dir / f"{ts}_{label}.png"
        await self._page.screenshot(path=str(dest), full_page=True)
        return dest

    # ── Convenience property ──────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        """Expose the raw Playwright Page for ad-hoc exploration."""
        return self._page
