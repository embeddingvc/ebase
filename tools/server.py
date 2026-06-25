"""
LinkedIn MCP server (live-only).

Exposes LinkedIn browser automation as MCP tools so Claude — or any MCP
host — can drive outreach workflows.

Drives a real Chrome browser via Playwright CDP. Chrome must be running with
--remote-debugging-port=9222 and the user must be logged in to LinkedIn
manually.

Quick start:
  make browser          # or launch Chrome with the flags above
  uv run tools/server.py

A mock-capable fork of this server (scripted responses, no browser) lives in
``testing/tools/server.py`` for regression runs and the QA dashboard.

── Tools ─────────────────────────────────────────────────────────────────────

  [LinkedIn actions]
    scrape_profile            Scrape a profile → structured JSON.
    parse_profile             Structured multi-page parse (v2 schema; no raw page dump).
    is_first_degree_connection  Check whether a profile is a 1st-degree connection.
      (Driven by the cron scheduler's deterministic connection sync sweep —
      see cron/connection_sync_sweep.py — and ad-hoc operator invocations.)
    send_connection_request   Send a connection request with an optional note.
    send_message              Send a DM to a 1st-degree connection.
    fetch_chat_history        Read the DM thread for a connection.
    create_new_post           Publish a new post from the home feed.
    reply_to_post             Leave a comment on a LinkedIn post.
    browse_forever            Start a background human-like browsing session.

  [outreach filesystem; paths are resolved inside the server]
    Data is rooted at outreach/ (live operator tree).

    get_connections           Return .../connections.json as JSON text.
    get_conversation_planner_config Return runtime planner config JSON.
    get_style_example_prompts Return tone + style-example questionnaire for setup-outreach.
    merge_conversation_planner_identity Merge persona / organization into .../config/persona.json (filesystem only; host LLM summarizes first).
    get_prospect              Return .../prospects/<id>.json as text.
    get_conversation          Return .../conversations/<id>.json as text.
    upsert_conversation_planner_config Write runtime planner config from JSON string.
    upsert_prospect           Write .../prospects/<id>.json from JSON string.
    save_connection           Upsert one row in .../connections.json.
    upsert_conversation       Write .../conversations/<id>.json from JSON string.
    schedule_meeting          Book or reserve a call after email + time are known.
    append_action_log         Append one JSON line to .../logs/actions.jsonl.
    append_planned_message_log Append one JSON line to planned_messages.jsonl.
    save_outreach_report      Write .../storage/reports/<id>.md.
    get_cron_status           Cron scheduler health, sweep config, and recent activity (JSON).
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

# Make the project root importable (outreach package) plus tools/ itself
# (notify, rate_limits).
_ROOT = Path(__file__).parent.parent
sys.path.append(str(_ROOT))
sys.path.append(str(Path(__file__).parent))

# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "server.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("linkedin.server")

# ── Background upgrade check ─────────────────────────────────────────────────
# Non-blocking: fires a daemon thread that shells out to bin/outreach-update-check
# and logs the result.  Never blocks mcp.run(); dies with the process.

_upgrade_info: dict = {}


def _run_upgrade_check() -> None:
    """Shell out to bin/outreach-update-check and log the result."""
    import subprocess

    check_bin = _ROOT / "bin" / "outreach-update-check"
    if not check_bin.is_file():
        return

    try:
        result = subprocess.run(
            [str(check_bin)],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_ROOT),
            env={**__import__("os").environ, "OUTREACH_REPO_ROOT": str(_ROOT)},
        )
        line = (result.stdout or "").strip()
        if not line:
            return

        parts = line.split()
        status = parts[0] if parts else ""

        if status == "UPGRADE_AVAILABLE" and len(parts) >= 3:
            old, new = parts[1], parts[2]
            _upgrade_info.update(status="upgrade_available", old=old, new=new)
            logger.warning(
                "ebase v%s available (current: v%s). "
                "Run /outreach-upgrade or make upgrade.",
                new,
                old,
            )
        elif status == "JUST_UPGRADED" and len(parts) >= 3:
            old, new = parts[1], parts[2]
            _upgrade_info.update(status="just_upgraded", old=old, new=new)
            logger.info(
                "ebase upgraded from v%s to v%s.",
                old,
                new,
            )
        elif status == "UP_TO_DATE" and len(parts) >= 2:
            _upgrade_info.update(status="up_to_date", version=parts[1])
        else:
            _upgrade_info.update(status="unknown", raw=line)
    except subprocess.TimeoutExpired:
        logger.debug("Upgrade check timed out (15s) — skipping.")
    except Exception:
        logger.debug("Upgrade check failed — skipping.", exc_info=True)


import threading as _threading

_upgrade_thread = _threading.Thread(target=_run_upgrade_check, daemon=True)
_upgrade_thread.start()

# ── MCP imports ──────────────────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

import notify as _notify                # tools/notify.py
from outreach.browser import LinkedInBrowser
from rate_limits import rate_limit

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "linkedin",
    instructions=(
        "Controls a LinkedIn browser session via Playwright CDP. "
    ),
)

# ── Background task handle ────────────────────────────────────────────────────

_browse_task: asyncio.Task | None = None
_browse_lock = asyncio.Lock()


def _outreach_base() -> Path:
    """Root directory for outreach filesystem MCP tools (live tree)."""
    return _ROOT / "outreach"


# ═════════════════════════════════════════════════════════════════════════════
# LINKEDIN TOOLS (drive the browser via Playwright CDP)
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def scrape_profile(
    profile_url: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Scrape a LinkedIn profile and return structured data as JSON.

    Navigates to the given LinkedIn profile URL, extracts key fields (name,
    headline, location, connection degree, about section, recent posts), then
    returns them as a JSON string matching the prospect schema used by the
    outreach planner.


    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL, e.g. "https://www.linkedin.com/in/username/".
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        JSON-encoded prospect dict with keys:
        linkedin_url, name, title, location, connection_degree,
        about, recent_posts, scraped_at.
    """
    err = rate_limit("profile_view", profile_url=profile_url, record=False)
    if err:
        return err

    logger.info("scrape_profile called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        profile = await li.scrape_profile(profile_url)
    rate_limit("profile_view", profile_url=profile_url, record=True)
    logger.info("scrape_profile finished  name=%s", profile.get("name"))
    return json.dumps(profile, ensure_ascii=False, indent=2)


@mcp.tool()
async def parse_profile(
    profile_url: str,
    cdp_url: str = "http://localhost:9222",
    max_activity_posts: int = 12,
    detail_scroll_rounds: int = 2,
    activity_extra_scroll_rounds: int = 3,
) -> str:
    """
    Parse a LinkedIn profile with a multi-step crawl (dynamic “relations + activity” pass).

    Live mode walks several routes (overview, ``details/*`` lists, mutual strip, then
    ``recent-activity/all`` with extra scrolling). Unlike :func:`scrape_profile`, the
    payload is **analysed**: slot-filled experience/education/skill/recommendation
    objects, identity + narrative + ``career_signals``, activity items with text
    metrics — **no** full-page ``raw_text`` or other unsegmented dumps.

    Returns JSON (schema ``linkedin.parse_profile/v2``):

    - ``subject`` — ``identity`` (url, ``public_id``, name, headline, location,
      network degree/label), ``narrative`` (about + character/word counts),
      ``career_signals`` (primary role/org/tenure + skills preview).
    - ``relations`` — structured ``experience``, ``education``, ``skills``,
      ``recommendations``, ``mutual_connections`` (``display_name`` objects), and
      ``rollup`` counts.
    - ``activity`` — ``feed_url``, ``stats`` (aggregate metrics), ``updates`` (each
      with ``body``, ``metrics``, ``engagement``).
    - ``crawl_log`` — crawl phases for debugging.
    - ``meta`` — ``parsed_at`` and schema id.

    Mock mode: returns the same envelope with fixture-backed values (no browser).

    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL, e.g. "https://www.linkedin.com/in/username/".
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".
    max_activity_posts : int
        Maximum activity feed update bodies to collect (default 12).
    detail_scroll_rounds : int
        Down-scroll iterations on each ``details/*`` page (default 2).
    activity_extra_scroll_rounds : int
        Extra scroll passes on the activity feed after the first (default 3).

    Returns
    -------
    str
        JSON object with ``subject``, ``relations``, ``activity``, ``crawl_log``, ``meta``.
    """
    err = rate_limit("profile_view", profile_url=profile_url, record=False)
    if err:
        return err

    logger.info(
        "parse_profile called  url=%s  cdp=%s  max_activity_posts=%s",
        profile_url,
        cdp_url,
        max_activity_posts,
    )
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        parsed = await li.parse_profile(
            profile_url,
            max_activity_posts=max_activity_posts,
            detail_scroll_rounds=detail_scroll_rounds,
            activity_extra_scroll_rounds=activity_extra_scroll_rounds,
        )
    rate_limit("profile_view", profile_url=profile_url, record=True)
    subj = parsed.get("subject") or {}
    ident = subj.get("identity") or {}
    act = parsed.get("activity") or {}
    logger.info(
        "parse_profile finished  name=%s  updates=%s",
        ident.get("full_name"),
        (act.get("stats") or {}).get("updates_collected"),
    )
    return json.dumps(parsed, ensure_ascii=False, indent=2)


@mcp.tool()
async def is_first_degree_connection(
    profile_url: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Check whether the signed-in LinkedIn member is a 1st-degree connection of
    the given profile (DM-capable without InMail).

    Live mode: opens the profile in the attached browser and uses the same
    heuristics as ``LinkedInBrowser.is_first_degree_connection`` (degree badge
    plus Message CTA fallback).

    Mock mode: returns JSON with ``first_degree`` true only when the active test
    case has ``connection_accepted`` and the session has moved past a cold state
    (connection invite recorded or the thread has any messages).

    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL.
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        JSON object: {"first_degree": bool, "profile_url": str}
    """
    err = rate_limit("profile_view", profile_url=profile_url, record=False)
    if err:
        return err

    logger.info(
        "is_first_degree_connection called  url=%s  cdp=%s", profile_url, cdp_url
    )
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        first = await li.is_first_degree_connection(profile_url)
    rate_limit("profile_view", profile_url=profile_url, record=True)
    out = {
        "first_degree": first,
        "profile_url": profile_url.strip(),
    }
    logger.info(
        "is_first_degree_connection finished  url=%s  first_degree=%s",
        profile_url,
        first,
    )
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
async def send_connection_request(
    profile_url: str,
    note: str = "",
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Send a connection request to a LinkedIn profile, with an optional note.

    Navigates to the given profile, clicks the Connect button (or opens the
    More overflow menu if Connect is not directly visible), optionally adds a
    personalised note (≤300 chars), and submits the invitation.


    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL.
    note : str
        Personalised connection note (LinkedIn limit: 300 chars).
        Pass an empty string to send without a note.
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    if len(note) > 300:
        return (
            f"Note too long: {len(note)} chars (LinkedIn limit: 300). "
            "Please shorten and retry."
        )

    err = rate_limit("connection_request", profile_url=profile_url, record=False)
    if err:
        return err

    logger.info(
        "send_connection_request called  url=%s  note_len=%d  cdp=%s",
        profile_url, len(note), cdp_url,
    )
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        success = await li.send_connection_request(profile_url, note=note)
    if success:
        rate_limit("connection_request", profile_url=profile_url, record=True)
        logger.info("send_connection_request finished  url=%s", profile_url)
        return "ok"
    return (
        "Connection request could not be sent. "
        "The Connect button was not found — the profile may already be a "
        "connection, have a pending request, or the button is hidden behind "
        "the More menu."
    )


@mcp.tool()
async def send_message(
    profile_url: str,
    message: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Send a direct message to an existing 1st-degree LinkedIn connection.

    Navigates to ``https://www.linkedin.com/messaging/``, resolves the
    conversation for the given profile URL, types the message at human-like
    speed, and submits it.


    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL.
    message : str
        Message body to send (LinkedIn limit: ~8 000 chars).
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    err = rate_limit("dm", profile_url=profile_url, record=False)
    if err:
        return err

    logger.info("send_message called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        search_name = _lookup_connection_name(profile_url)
        success = await li.send_message(profile_url, message, search_name=search_name)
    if success:
        rate_limit("dm", profile_url=profile_url, record=True)
        logger.info("send_message finished  url=%s", profile_url)
        return "ok"
    return (
        "Message could not be sent. "
        "The profile may not be a 1st-degree connection, "
        "or the Message button was not found."
    )


@mcp.tool()
async def fetch_chat_history(
    profile_url: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Load the visible direct-message thread for a 1st-degree connection.

    Opens ``https://www.linkedin.com/messaging/`` and smart-navigates to the
    target conversation, then returns message bubbles currently in the DOM
    (older history may require scrolling in the UI).


    Parameters
    ----------
    profile_url : str
        Full LinkedIn profile URL.
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        JSON array: [{"message": str, "self": bool}, …]
        "self": true  = sent by operator (us)
        "self": false = sent by prospect
    """
    logger.info("fetch_chat_history called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        search_name = _lookup_connection_name(profile_url)
        items = await li.fetch_chat_history(profile_url, search_name=search_name)
    logger.info(
        "fetch_chat_history finished  url=%s  count=%d", profile_url, len(items)
    )
    return json.dumps(items, ensure_ascii=False, indent=2)


@mcp.tool()
async def create_new_post(
    content: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Create and publish a new LinkedIn post from the home feed.

    Navigates to the feed, opens "Start a post", types the body in the
    composer modal, and clicks Post.

    Parameters
    ----------
    content : str
        Text to publish (non-empty; keep within LinkedIn length limits).
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    text = (content or "").strip()
    logger.info("create_new_post called  content_len=%d  cdp=%s", len(text), cdp_url)
    try:
        async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
            await li.assert_logged_in()
            success = await li.create_new_post(text)
    except ValueError as exc:
        return str(exc)
    if success:
        logger.info("create_new_post finished")
        return "ok"
    return (
        "Post could not be published. "
        'Open the LinkedIn feed in Chrome and ensure "Start a post" and the '
        "composer modal load correctly."
    )


@mcp.tool()
async def reply_to_post(
    post_url: str,
    comment: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Leave a comment (reply) on a LinkedIn post.

    Navigates to the post URL, opens the comment composer, types the comment
    at human-like speed, and submits it.

    Parameters
    ----------
    post_url : str
        Direct URL of the LinkedIn post or activity item.
    comment : str
        Comment text to post.
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    logger.info("reply_to_post called  url=%s  cdp=%s", post_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        success = await li.comment_on_post(post_url, comment)
    if success:
        logger.info("reply_to_post finished  url=%s", post_url)
        return "ok"
    return (
        "Comment could not be posted. "
        "The Comment button was not found on the post page."
    )


@mcp.tool()
async def download_profile_pdf(
    profile_url: str,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Download a LinkedIn profile as PDF via the UI action: More → Save to PDF.

    Saves the file to ./profiles/ in the project root and returns JSON:
      {"ok": true, "profile_url": "...", "filename": "<uuid>.pdf", "path": "..."}
    """
    filename = f"{uuid.uuid4()}.pdf"
    save_dir = _ROOT / "profiles"

    err = rate_limit("profile_view", profile_url=profile_url, record=False)
    if err:
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False, indent=2)

    logger.info("download_profile_pdf called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        path = await li.download_profile_pdf(profile_url, save_dir=save_dir, filename=filename)

    rate_limit("profile_view", profile_url=profile_url, record=True)
    out = {
        "ok": True,
        "profile_url": profile_url.strip(),
        "filename": filename,
        "path": str(path),
    }
    logger.info("download_profile_pdf finished  file=%s", path)
    return json.dumps(out, ensure_ascii=False, indent=2)


@mcp.tool()
async def browse_forever(
    reaction: str = "Like",
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Start a human-like LinkedIn browsing session that runs indefinitely in the
    background until the MCP server process exits or receives SIGINT/SIGTERM.

    Each round the session will:
      - Navigate to (or stay on) the LinkedIn feed.
      - Read through 3–7 posts with realistic per-post dwell times (8–35 s).
      - Occasionally click into a post for a deeper read, then go back.
      - React randomly to ~20 % of feed posts inline (no URL needed).
      - Take a 2–6 minute idle break before the next round.

    Parameters
    ----------
    reaction : str
        Reaction type applied randomly while scrolling the feed (~20 % of posts).
        One of: Like, Celebrate, Support, Funny, Love, Insightful.
    cdp_url : str
        Chrome DevTools Protocol endpoint. Defaults to "http://localhost:9222".

    Returns
    -------
    str
        Confirmation that the session was started, or a notice that one is
        already running.
    """
    global _browse_task

    async with _browse_lock:
        if _browse_task is not None and not _browse_task.done():
            logger.warning("browse_forever: session already running")
            return (
                "A browse_forever session is already running. "
                "It will stop when the server process exits or receives SIGINT/SIGTERM."
            )

        async def _run() -> None:
            logger.info(
                "browse_forever session started  cdp=%s  reaction=%s",
                cdp_url, reaction,
            )
            try:
                async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
                    await li.assert_logged_in()
                    await li.browse_forever(reaction=reaction)
            except Exception:
                logger.exception("browse_forever session ended with an error")
                raise
            else:
                logger.info("browse_forever session finished cleanly")

        loop = asyncio.get_event_loop()
        _browse_task = loop.create_task(_run())

    logger.info(
        "browse_forever task created  cdp=%s  reaction=%s", cdp_url, reaction
    )
    return (
        f"browse_forever started — reaction={reaction!r}, cdp={cdp_url}. "
        "The session runs in the background until the server process exits."
    )


# ═════════════════════════════════════════════════════════════════════════════
# OUTREACH FILE-MANAGEMENT TOOLS
# These tools always write under _outreach_base() (outreach/) so skills never
# need to guess paths or run bash scripts.
# ═════════════════════════════════════════════════════════════════════════════

import tempfile
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _parse_schedule_datetime(raw: str) -> datetime | None:
    """Parse an ISO 8601 instant (``...Z`` or with offset) into a UTC datetime."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _planner_config_path() -> Path:
    return _outreach_base() / "config" / "conversation_planner.json"


def _persona_path() -> Path:
    return _outreach_base() / "config" / "persona.json"


def _style_example_prompts_path() -> Path:
    return _outreach_base() / "config" / "style_example_prompts.json"


def _bundled_style_example_prompts_path() -> Path:
    return Path(__file__).resolve().parent.parent / "outreach" / "config" / "style_example_prompts.json"


def _load_style_example_prompts() -> dict:
    """Load tone + style-example questionnaire for setup flows."""
    for path in (_style_example_prompts_path(), _bundled_style_example_prompts_path()):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("_load_style_example_prompts: invalid %s", path)
            continue
        if isinstance(data, dict):
            return data
    return {"version": 1, "tone_questions": [], "style_example_prompts": []}


_ALLOWED_PLANNER_PERSONA_KEYS = frozenset({"name", "role", "organization", "specialization"})
_ALLOWED_PLANNER_ORGANIZATION_KEYS = frozenset({"description"})


def _default_planner_identity() -> dict:
    """Default persona + organization when persona.json is missing or partial."""
    return {
        "persona": {
            "name": "Nova Chen",
            "role": "virtual team member",
            "organization": "Embedding VC",
            "specialization": "AI research and operations",
        },
        "organization": {
            "description": (
                "We back early-stage AI startups and connect top talent with great AI companies."
            ),
        },
    }


def _load_planner_identity() -> dict:
    """
    Load merged identity for MCP responses and merges.

    Reads ``persona.json`` under the active outreach data root when present;
    unknown keys are ignored. Missing inner keys are filled from defaults.
    """
    base = copy.deepcopy(_default_planner_identity())
    persona_path = _persona_path()
    if not persona_path.exists():
        return base
    try:
        data = json.loads(persona_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("_load_planner_identity: invalid or unreadable %s", persona_path)
        return base
    if not isinstance(data, dict):
        return base
    p_raw = data.get("persona")
    o_raw = data.get("organization")
    if isinstance(p_raw, dict):
        for key, val in p_raw.items():
            if key in _ALLOWED_PLANNER_PERSONA_KEYS and isinstance(val, str):
                base["persona"][key] = val
            elif key in _ALLOWED_PLANNER_PERSONA_KEYS and val is None:
                continue
    if isinstance(o_raw, dict):
        for key, val in o_raw.items():
            if key in _ALLOWED_PLANNER_ORGANIZATION_KEYS and isinstance(val, str):
                base["organization"][key] = val
            elif key in _ALLOWED_PLANNER_ORGANIZATION_KEYS and val is None:
                continue
    return base


def _strip_legacy_identity_from_core(cfg: dict) -> None:
    """Drop persona/organization from on-disk planner JSON (legacy placement)."""
    cfg.pop("persona", None)
    cfg.pop("organization", None)


def _compose_public_planner_config(core: dict) -> dict:
    """Merge core planner fields with identity for get_conversation_planner_config."""
    identity = _load_planner_identity()
    return {
        "persona": identity["persona"],
        "organization": identity["organization"],
        **core,
    }


def _default_conversation_planner_config() -> dict:
    """Planner defaults without persona (those live in persona.json)."""
    return {
        "campaign": {
            "goal": "Recruit strong AI and software talent for portfolio opportunities.",
            "topic": "AI startup opportunities and career exploration",
            "value_proposition": (
                "high-context introductions to startups where candidate background maps to real needs"
            ),
        },
        "conversation_end_goals": {
            "preferred": [
                {
                    "id": "resume_received",
                    "label": "Collect resume",
                    "description": "Prospect shares resume for matching.",
                },
                {
                    "id": "call_scheduled",
                    "label": "Schedule meeting",
                    "description": "Prospect agrees to a call and shares scheduling details.",
                },
            ],
            "fallback": [
                {"id": "not_interested", "label": "Prospect not interested"},
                {"id": "no_response", "label": "No response timeout"},
            ],
        },
        "message_rules": {
            "connection_note_char_limit": 200,
            "followup_char_limit": 300,
            "must_include_first_name": True,
            "banned_phrases": [
                "I came across your profile",
                "I'd love to pick your brain",
                "synergy",
                "hope this message finds you",
                "reaching out to connect",
                "touching base",
                "circle back",
                "bandwidth",
            ],
            "tone": "warm, specific, curious, low-pressure",
            "tone_guidelines": "",
            "style_examples": [],
        },
        "router": {
            "default_plan_mode": "full_sequence",
            "step_timeout_hours": 48,
            "step4_path_priority": [
                "resume_received",
                "call_scheduled",
            ],
            "signal_routes": {
                "disinterest": {
                    "next_action": "mark_dead",
                    "ended_reason": "not_interested",
                },
                "no_response_timeout": {
                    "next_action": "mark_dead",
                    "ended_reason": "no_response",
                },
                "resume_or_artifact_received": {
                    "force_sequence_step": 5,
                    "preferred_goal_id": "resume_received",
                },
                "email_or_call_intent": {
                    "force_sequence_step": 4,
                    "preferred_goal_id": "call_scheduled",
                },
            },
        },
    }


def _validate_conversation_planner_config(config: dict) -> str | None:
    if not isinstance(config, dict):
        return "config must be a JSON object"

    if "persona" in config or "organization" in config:
        return (
            "persona and organization are stored in persona.json (under the active outreach data root); "
            "remove them from this payload and use merge_conversation_planner_identity, "
            "or edit persona.json directly"
        )

    for key in (
        "campaign",
        "conversation_end_goals",
        "message_rules",
        "router",
    ):
        if key in config and not isinstance(config[key], dict):
            return f"{key} must be an object"

    for key in ("connection_note_char_limit", "followup_char_limit"):
        value = (
            config.get("message_rules", {}).get(key)
            if isinstance(config.get("message_rules"), dict)
            else None
        )
        if value is not None and (not isinstance(value, int) or value <= 0):
            return f"message_rules.{key} must be a positive integer"

    rules = config.get("message_rules")
    if isinstance(rules, dict):
        guidelines = rules.get("tone_guidelines")
        if guidelines is not None and not isinstance(guidelines, str):
            return "message_rules.tone_guidelines must be a string"

        examples = rules.get("style_examples")
        if examples is not None:
            if not isinstance(examples, list):
                return "message_rules.style_examples must be an array"
            for idx, item in enumerate(examples):
                if not isinstance(item, dict):
                    return (
                        f"message_rules.style_examples[{idx}] must be an object"
                    )
                reply = item.get("reply")
                if not isinstance(reply, str) or not reply.strip():
                    return (
                        f"message_rules.style_examples[{idx}].reply must be a "
                        "non-empty string"
                    )
                for opt_key in ("label", "context", "incoming"):
                    val = item.get(opt_key)
                    if val is not None and not isinstance(val, str):
                        return (
                            f"message_rules.style_examples[{idx}].{opt_key} "
                            "must be a string when set"
                        )

    end_goals = config.get("conversation_end_goals")
    if isinstance(end_goals, dict):
        for bucket in ("preferred", "fallback"):
            items = end_goals.get(bucket)
            if items is None:
                continue
            if not isinstance(items, list):
                return f"conversation_end_goals.{bucket} must be an array"
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    return (
                        f"conversation_end_goals.{bucket}[{idx}] must be an object"
                    )
                if not item.get("id"):
                    return (
                        f"conversation_end_goals.{bucket}[{idx}].id is required"
                    )

    router = config.get("router")
    if isinstance(router, dict):
        timeout = router.get("step_timeout_hours")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            return "router.step_timeout_hours must be a positive integer"
        priorities = router.get("step4_path_priority")
        if priorities is not None:
            if not isinstance(priorities, list) or not all(
                isinstance(item, str) and item.strip() for item in priorities
            ):
                return "router.step4_path_priority must be an array of non-empty strings"
        routes = router.get("signal_routes")
        if routes is not None and not isinstance(routes, dict):
            return "router.signal_routes must be an object"

    return None


def _normalize_prospect_id_slug(raw: str | None) -> str | None:
    """Lowercase slug matching prospect.schema id pattern ^[a-z0-9_]+$."""
    if raw is None or not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    if not s or len(s) > 200:
        return None
    return s


def _derive_prospect_id_from_profile_url(profile_url: str) -> str | None:
    """Extract /in/<handle>/ from a LinkedIn profile URL and normalize to prospect_id."""
    try:
        path = urlparse(profile_url.strip()).path
        m = re.search(r"/in/([^/?#]+)", path, re.I)
        if not m:
            return None
        return _normalize_prospect_id_slug(m.group(1))
    except Exception:
        return None


def _sanitize_connection_name(name: str | None) -> str:
    """
    Keep only a clean person name for storage/search.
    """
    text = (name or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+#\S.*$", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


_CONNECTION_STATUSES = frozenset({"pending", "connected", "ended"})
_TERMINAL_CONVERSATION_STAGES = frozenset({"ended", "dead"})


def _mark_connection_ended(
    prospect_id: str,
    profile_url: str | None = None,
) -> bool:
    """
    Set ``connection_status`` to ``ended`` for the matching row in connections.json.
    Preserves ``connected_at`` when the row was previously ``connected``.
    """
    path = _outreach_base() / "connections.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("_mark_connection_ended: could not read %s", path)
        return False
    rows = data.get("connections")
    if not isinstance(rows, list):
        return False
    pid = _normalize_prospect_id_slug(prospect_id)
    norm_url = (profile_url or "").strip().rstrip("/")
    updated = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_pid = _normalize_prospect_id_slug(row.get("prospect_id"))
        row_url = (row.get("profile_url") or "").strip().rstrip("/")
        if (pid and row_pid == pid) or (norm_url and row_url == norm_url):
            if row.get("connection_status") == "ended":
                return False
            row["connection_status"] = "ended"
            updated = True
            break
    if updated:
        _atomic_write_json(path, data)
        logger.info(
            "_mark_connection_ended: prospect_id=%s profile_url=%s",
            prospect_id,
            profile_url,
        )
    return updated


def _sync_prospect_outreach_stage(prospect_id: str, stage: str) -> None:
    """Align prospects/<id>.json outreach_stage with a terminal conversation stage."""
    if stage not in _TERMINAL_CONVERSATION_STAGES:
        return
    path = _outreach_base() / "prospects" / f"{prospect_id}.json"
    if not path.is_file():
        return
    try:
        prospect = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(prospect, dict):
            return
        if prospect.get("outreach_stage") in _TERMINAL_CONVERSATION_STAGES:
            return
        prospect["outreach_stage"] = stage
        _atomic_write_json(path, prospect)
        logger.info("_sync_prospect_outreach_stage: %s → %s", prospect_id, stage)
    except (OSError, json.JSONDecodeError):
        logger.exception("_sync_prospect_outreach_stage failed for %s", prospect_id)


def _notify_conversation_ended(prospect_id: str, conversation: object) -> str:
    """
    Email the operator that a conversation just transitioned into a terminal stage.

    Returns the notifier status string (``"sent"`` / ``"skipped"`` / ``"error: ..."``).
    Never raises: SMTP failures are logged and swallowed so the calling upsert
    is not rolled back.
    """
    data = conversation if isinstance(conversation, dict) else {}
    stage = str(data.get("outreach_stage") or "")
    linkedin_url = data.get("linkedin_url") if isinstance(data, dict) else None
    prospect_name, resolved_url = _lookup_prospect_identity(
        prospect_id, linkedin_url if isinstance(linkedin_url, str) else None
    )
    sequence_step = data.get("sequence_step")
    if not isinstance(sequence_step, int):
        sequence_step = None
    try:
        status = _notify.send_conversation_ended_email(
            prospect_id=prospect_id,
            prospect_name=prospect_name,
            profile_url=resolved_url,
            outreach_stage=stage,
            ended_reason=str(data.get("ended_reason") or ""),
            ended_at=str(data.get("ended_at") or ""),
            sequence_step=sequence_step,
            report_path=(
                str(data.get("report_path"))
                if isinstance(data.get("report_path"), str)
                else None
            ),
            end_goal=(
                str(data.get("end_goal"))
                if isinstance(data.get("end_goal"), str)
                else None
            ),
        )
    except Exception as exc:
        logger.exception(
            "_notify_conversation_ended: notifier raised for %s", prospect_id
        )
        return f"error: {exc}"
    logger.info(
        "_notify_conversation_ended: prospect_id=%s stage=%s status=%s",
        prospect_id,
        stage,
        status,
    )
    return status


def _lookup_connection_name(profile_url: str) -> str | None:
    """
    Read clean name for a profile URL from connections.json under the active outreach root.
    """
    path = _outreach_base() / "connections.json"
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("connections", [])
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and row.get("profile_url") == profile_url:
                name = _sanitize_connection_name(row.get("name"))
                return name or None
    except Exception:
        logger.exception("_lookup_connection_name failed")
    return None


def _atomic_write_json(path: Path, data: object) -> None:
    """Write JSON atomically via temp-file + rename so a crash cannot corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        Path(tmp).replace(path)
    except Exception:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
        raise


@mcp.tool()
async def get_connections() -> str:
    """
    Read connections.json from the outreach data directory (outreach/).
    Skills must use this instead of constructing paths.
    """
    path = _outreach_base() / "connections.json"
    try:
        if not path.exists():
            return json.dumps({"connections": []}, indent=2, ensure_ascii=False) + "\n"
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_connections failed")
        return f"error: {exc}"


@mcp.tool()
async def get_prospect(prospect_id: str) -> str:
    """Read prospects/<prospect_id>.json under the active outreach data root as UTF-8 text."""
    path = _outreach_base() / "prospects" / f"{prospect_id}.json"
    try:
        if not path.exists():
            return f"error: prospect not found: {prospect_id}"
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_prospect failed")
        return f"error: {exc}"


@mcp.tool()
async def get_conversation(prospect_id: str) -> str:
    """Read conversations/<prospect_id>.json under the active outreach data root as UTF-8 text."""
    path = _outreach_base() / "conversations" / f"{prospect_id}.json"
    try:
        if not path.exists():
            return f"error: conversation not found: {prospect_id}"
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_conversation failed")
        return f"error: {exc}"


@mcp.tool()
async def save_connection(
    profile_url: str,
    name: str,
    title: str = "",
    prospect_id: str | None = None,
    note_sent: str | None = None,
    connection_status: str = "pending",
) -> str:
    """
    Upsert a connection entry in connections.json under the active outreach data root.

    Always writes to the correct project folder regardless of which directory the
    skill or scheduled task runs from.  If an entry with the same profile_url already
    exists it is replaced (never duplicated).

    Parameters
    ----------
    profile_url : str
        LinkedIn profile URL — used as the unique key.
    name : str
        Full name scraped from the profile.
    title : str
        Job title / headline scraped from the profile.
    prospect_id : str | None
        Pipeline prospect ID (must match prospects/<id>.json under the active outreach root). If omitted or null, the id is
        taken from an existing row for the same profile_url, else derived from the URL path
        (``/in/handle/`` → ``handle`` with hyphens → underscores). This keeps batch conversation-planner
        runs working after ad-hoc connection sends.
    note_sent : str | None
        The connection note that was sent, or None if no note was included.
    connection_status : str
        "pending" (default) until LinkedIn accepts; then "connected"; "ended" when the
        outreach sequence is complete for this row (batch planner skips ended rows).

    Returns
    -------
    str
        Confirmation string on success, or an error description.
    """
    status = (connection_status or "pending").strip()
    if status not in _CONNECTION_STATUSES:
        return f"error: invalid connection_status {status!r}; expected one of {sorted(_CONNECTION_STATUSES)}"

    path = _outreach_base() / "connections.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if "connections" not in data or not isinstance(data["connections"], list):
                data["connections"] = []
        else:
            data = {"connections": []}

        connections = data["connections"]
        idx = next((i for i, c in enumerate(connections) if c.get("profile_url") == profile_url), None)
        previous: dict | None = connections[idx] if idx is not None else None

        explicit = _normalize_prospect_id_slug(prospect_id)
        previous_pid = _normalize_prospect_id_slug((previous or {}).get("prospect_id"))
        derived = _derive_prospect_id_from_profile_url(profile_url)
        resolved_pid = explicit or previous_pid or derived

        clean_name = _sanitize_connection_name(name) or name.strip()
        connected_at = _iso_now()
        if previous and previous.get("connected_at"):
            if status == "ended" or (
                status == "connected" and previous.get("connection_status") == "connected"
            ):
                connected_at = previous["connected_at"]

        entry = {
            "prospect_id": resolved_pid,
            "profile_url": profile_url,
            "name": clean_name,
            "title": title,
            "connection_status": status,
            "connected_at": connected_at,
            "note_sent": note_sent,
        }

        if idx is not None:
            connections[idx] = entry
        else:
            connections.append(entry)

        _atomic_write_json(path, data)
        logger.info(
            "save_connection: saved %s prospect_id=%s → %s",
            clean_name,
            resolved_pid,
            path,
        )
        return (
            f"ok — saved {clean_name} ({profile_url}) prospect_id={resolved_pid!r} to {path}"
        )
    except Exception as exc:
        logger.exception("save_connection failed")
        return f"error: {exc}"


def _lookup_prospect_identity(
    prospect_id: str,
    profile_url: str | None,
) -> tuple[str, str]:
    """
    Resolve ``(display_name, profile_url)`` for a prospect for notification copy.

    Reads ``connections.json`` first (fast, single file), then falls back to
    ``prospects/<id>.json``. Returns empty strings rather than failing so the
    notifier can still send a useful subject/body.
    """
    name = ""
    url = (profile_url or "").strip()
    conn_path = _outreach_base() / "connections.json"
    if conn_path.is_file():
        try:
            data = json.loads(conn_path.read_text(encoding="utf-8"))
            rows = data.get("connections") if isinstance(data, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    row_pid = _normalize_prospect_id_slug(row.get("prospect_id"))
                    row_url = (row.get("profile_url") or "").strip()
                    if (row_pid and row_pid == prospect_id) or (url and row_url == url):
                        name = _sanitize_connection_name(row.get("name")) or name
                        url = url or row_url
                        break
        except (OSError, json.JSONDecodeError):
            logger.exception("_lookup_prospect_identity: could not read %s", conn_path)

    if not name or not url:
        prospect_path = _outreach_base() / "prospects" / f"{prospect_id}.json"
        if prospect_path.is_file():
            try:
                prospect = json.loads(prospect_path.read_text(encoding="utf-8"))
                if isinstance(prospect, dict):
                    name = name or _sanitize_connection_name(prospect.get("name")) or ""
                    url = url or (prospect.get("linkedin_url") or "").strip()
            except (OSError, json.JSONDecodeError):
                logger.exception(
                    "_lookup_prospect_identity: could not read %s", prospect_path
                )

    return name, url


async def _schedule_meeting_live(
    email: str,
    datetime: str,
    prospect_id: str | None = None,
    profile_url: str | None = None,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Live ``schedule_meeting``: validate inputs, persist email + meeting state on
    the prospect's conversation file, append an action log entry, and email the
    operator if SMTP is configured. No real calendar integration yet —
    ``meeting_link`` defaults to ``""`` and the operator books the invite
    manually using the email + ``scheduled_at`` from the notification.
    """
    del cdp_url

    email_clean = (email or "").strip()
    if not email_clean or not _EMAIL_RE.match(email_clean):
        return "error: invalid email"

    dt = _parse_schedule_datetime(datetime)
    if dt is None:
        return "error: invalid datetime"

    pid = _normalize_prospect_id_slug(prospect_id)
    if not pid and profile_url:
        pid = _derive_prospect_id_from_profile_url(profile_url)
    if not pid:
        return "error: prospect context required"

    scheduled_at = dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    meeting_link = ""

    conv_path = _outreach_base() / "conversations" / f"{pid}.json"
    if conv_path.is_file():
        try:
            conv = json.loads(conv_path.read_text(encoding="utf-8"))
            if not isinstance(conv, dict):
                conv = {}
        except (OSError, json.JSONDecodeError):
            logger.exception("_schedule_meeting_live: could not read %s", conv_path)
            conv = {}
    else:
        conv = {"prospect_id": pid, "messages": [], "outreach_stage": "engaged"}

    conv["prospect_id"] = pid
    conv["email"] = email_clean
    conv["meeting_link"] = meeting_link
    conv["last_action"] = "confirm_meeting"
    conv["last_action_timestamp"] = _iso_now()
    try:
        _atomic_write_json(conv_path, conv)
    except OSError as exc:
        logger.exception("_schedule_meeting_live: could not write %s", conv_path)
        return f"error: could not persist conversation: {exc}"

    action_entry = {
        "action": "schedule_meeting",
        "prospect_id": pid,
        "email": email_clean,
        "scheduled_at": scheduled_at,
        "meeting_link": meeting_link,
        "timestamp": _iso_now(),
    }
    try:
        log_path = _outreach_base() / "logs" / "actions.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(action_entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("_schedule_meeting_live: could not append action log")

    prospect_name, resolved_profile_url = _lookup_prospect_identity(pid, profile_url)
    notify_status = _notify.send_meeting_scheduled_email(
        prospect_id=pid,
        prospect_name=prospect_name,
        profile_url=resolved_profile_url,
        email=email_clean,
        scheduled_at=scheduled_at,
        meeting_link=meeting_link,
    )

    payload = {
        "status": "scheduled",
        "meeting_link": meeting_link,
        "scheduled_at": scheduled_at,
        "email": email_clean,
        "prospect_id": pid,
        "notified": notify_status == "sent",
        "notify_status": notify_status,
    }
    logger.info(
        "schedule_meeting LIVE  prospect_id=%s scheduled_at=%s notify=%s",
        pid,
        scheduled_at,
        notify_status,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
async def schedule_meeting(
    email: str,
    datetime: str,
    prospect_id: str | None = None,
    profile_url: str | None = None,
    cdp_url: str = "http://localhost:9222",
) -> str:
    """
    Book a calendar hold for a prospect after email and time are agreed.


    In live mode: not implemented — returns an explicit error (no silent success).

    Parameters
    ----------
    email : str
        Prospect email to invite.
    datetime : str
        ISO 8601 UTC instant for the meeting (e.g. ``2026-05-20T15:00:00Z``).
    prospect_id : str | None
        Outreach prospect id (preferred for filesystem updates).
    profile_url : str | None
        LinkedIn profile URL when ``prospect_id`` is unknown.
    cdp_url : str
        Reserved for future live calendar integration.

    Returns
    -------
    str
        JSON with scheduling fields on success, or ``error: ...`` on failure.
    """
    return await _schedule_meeting_live(
        email=email,
        datetime=datetime,
        prospect_id=prospect_id,
        profile_url=profile_url,
        cdp_url=cdp_url,
    )


@mcp.tool()
async def upsert_conversation(
    prospect_id: str,
    conversation: str,
) -> str:
    """
    Write (create or overwrite) a conversation JSON file under conversations/.

    Parameters
    ----------
    prospect_id : str
        The prospect ID — file will be saved as conversations/<prospect_id>.json under the active outreach root.
    conversation : str
        Full JSON string of the conversation object (must match conversation.schema.json).

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    path = _outreach_base() / "conversations" / f"{prospect_id}.json"
    prior_stage: str | None = None
    if path.is_file():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                raw_prior_stage = prior.get("outreach_stage")
                if isinstance(raw_prior_stage, str):
                    prior_stage = raw_prior_stage
        except (OSError, json.JSONDecodeError):
            logger.exception(
                "upsert_conversation: could not read prior state at %s", path
            )

    try:
        data = json.loads(conversation)
        _atomic_write_json(path, data)
        stage = data.get("outreach_stage") if isinstance(data, dict) else None
        if stage in _TERMINAL_CONVERSATION_STAGES:
            linkedin_url = (
                data.get("linkedin_url") if isinstance(data, dict) else None
            )
            _mark_connection_ended(prospect_id, linkedin_url)
            _sync_prospect_outreach_stage(prospect_id, str(stage))
            if prior_stage not in _TERMINAL_CONVERSATION_STAGES:
                _notify_conversation_ended(prospect_id, data)
        logger.info("upsert_conversation: wrote %s", path)
        return f"ok — wrote {path}"
    except Exception as exc:
        logger.exception("upsert_conversation failed")
        return f"error: {exc}"


@mcp.tool()
async def upsert_prospect(
    prospect_id: str,
    prospect: str,
) -> str:
    """
    Write (create or overwrite) prospects/<prospect_id>.json under the active outreach root.

    Parameters
    ----------
    prospect_id : str
        Filename stem; should match the ``id`` field inside ``prospect`` JSON.
    prospect : str
        Full JSON string of the prospect object (prospect.schema.json).
    """
    path = _outreach_base() / "prospects" / f"{prospect_id}.json"
    try:
        data = json.loads(prospect)
        _atomic_write_json(path, data)
        logger.info("upsert_prospect: wrote %s", path)
        return f"ok — wrote {path}"
    except Exception as exc:
        logger.exception("upsert_prospect failed")
        return f"error: {exc}"


@mcp.tool()
async def append_action_log(
    entry: str,
) -> str:
    """
    Append one JSON entry to logs/actions.jsonl under the active outreach data root.

    Parameters
    ----------
    entry : str
        A JSON object string to append as a single line.
        Should include at minimum: action, timestamp.

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    path = _outreach_base() / "logs" / "actions.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = json.loads(entry)  # validate it's real JSON before writing
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(parsed, ensure_ascii=False) + "\n")
        logger.info("append_action_log: wrote to %s", path)
        return "ok"
    except Exception as exc:
        logger.exception("append_action_log failed")
        return f"error: {exc}"


@mcp.tool()
async def append_planned_message_log(
    entry: str,
) -> str:
    """
    Append one JSON entry to logs/planned_messages.jsonl under the active outreach data root.

    Parameters
    ----------
    entry : str
        A JSON object string to append as a single line (PlannedMessage schema).

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    path = _outreach_base() / "logs" / "planned_messages.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = json.loads(entry)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(parsed, ensure_ascii=False) + "\n")
        logger.info("append_planned_message_log: wrote to %s", path)
        return "ok"
    except Exception as exc:
        logger.exception("append_planned_message_log failed")
        return f"error: {exc}"


@mcp.tool()
async def save_outreach_report(
    prospect_id: str,
    content: str,
) -> str:
    """
    Save an end-of-sequence outreach report to storage/reports/ under the active outreach root.

    Parameters
    ----------
    prospect_id : str
        Used as the filename: storage/reports/<prospect_id>.md
    content : str
        Full markdown content of the report.

    Returns
    -------
    str
        "ok — saved <path>" on success, or an error description.
    """
    path = _outreach_base() / "storage" / "reports" / f"{prospect_id}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("save_outreach_report: wrote %s", path)
        return f"ok — saved {path}"
    except Exception as exc:
        logger.exception("save_outreach_report failed")
        return f"error: {exc}"


@mcp.tool()
async def get_cron_status() -> str:
    """
    Return cron scheduler health, per-sweep configuration, and recent tick/run
    activity as JSON.

    Includes whether the cron HTTP server is reachable, whether a launchd/systemd
    auto-start unit is installed, configured sweeps (connection sync and
    conversation plan), and restart hints.
    """
    try:
        from cron.status_report import build_cron_status

        return json.dumps(build_cron_status(), indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.exception("get_cron_status failed")
        return f"error: {exc}"


@mcp.tool()
async def get_conversation_planner_config() -> str:
    """
    Read planner config from config/conversation_planner.json and identity from
    config/persona.json under the active outreach data root (optional; defaults apply if absent).

    Returns a single merged JSON object (persona + organization + campaign, rules,
    router) so callers keep one MCP read. Reads from disk on every call so manual
    edits are reflected immediately.
    """
    try:
        planner_path = _planner_config_path()
        if not planner_path.exists():
            core = _default_conversation_planner_config()
            _atomic_write_json(planner_path, core)
        else:
            core = json.loads(planner_path.read_text(encoding="utf-8"))
            if not isinstance(core, dict):
                return (
                    "error: "
                    + str(planner_path)
                    + " must contain a JSON object at top level"
                )
            _strip_legacy_identity_from_core(core)
        err = _validate_conversation_planner_config(core)
        if err:
            return f"error: {err}"
        merged = _compose_public_planner_config(core)
        return json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    except Exception as exc:
        logger.exception("get_conversation_planner_config failed")
        return f"error: {exc}"


@mcp.tool()
async def get_style_example_prompts() -> str:
    """
    Return the tone + style-example questionnaire used during setup-outreach.

    JSON shape:
    - ``tone_questions[]`` — short prompts that compile into ``message_rules.tone``
      and ``message_rules.tone_guidelines``.
    - ``style_example_prompts[]`` — outreach scenarios; each has ``question``,
      ``label``, ``context``, optional ``incoming``, and ``hint``. Collect only
      the operator's ``reply`` and merge the rest from the prompt object.

    Reads ``config/style_example_prompts.json`` under the active outreach data
    root, falling back to the repo template when absent.
    """
    try:
        data = _load_style_example_prompts()
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    except Exception as exc:
        logger.exception("get_style_example_prompts failed")
        return f"error: {exc}"


@mcp.tool()
async def upsert_conversation_planner_config(config: str) -> str:
    """
    Write config/conversation_planner.json under the active outreach data root from JSON string input.

    Does not accept ``persona`` or ``organization`` — those live in
    ``config/persona.json`` (see ``merge_conversation_planner_identity``).
    Performs lightweight structural validation and writes atomically so runtime
    reads always see a complete file.
    """
    try:
        parsed = json.loads(config)
        validation_error = _validate_conversation_planner_config(parsed)
        if validation_error:
            return f"error: {validation_error}"
        planner_path = _planner_config_path()
        _atomic_write_json(planner_path, parsed)
        logger.info("upsert_conversation_planner_config: wrote %s", planner_path)
        return f"ok — wrote {planner_path}"
    except Exception as exc:
        logger.exception("upsert_conversation_planner_config failed")
        return f"error: {exc}"


@mcp.tool()
async def merge_conversation_planner_identity(
    persona_json: str = "{}",
    organization_json: str = "{}",
) -> str:
    """
    Shallow-merge ``persona`` and/or ``organization`` into ``config/persona.json`` under the active outreach data root.

    Intended for Skills / LLM-authored updates: call MCP ``parse_profile`` first (host model
    reads the v2 envelope), decide ``persona`` + ``organization`` copy, then pass JSON blobs here.
    Omit keys by passing ``{}``. Unknown keys return an error. ``null`` values are ignored.

    Does **not** call LinkedIn; only merges into ``persona.json`` (fills missing fields from defaults).

    Parameters
    ----------
    persona_json : str
        JSON object with zero or more of: ``name``, ``role``, ``organization``, ``specialization``.
    organization_json : str
        JSON object with zero or more of: ``description`` (other keys rejected).

    Returns
    -------
    str
        JSON ``{ok, path, persona, organization}`` or ``{ok: false, error: ...}``.
    """
    try:
        pj = persona_json.strip() or "{}"
        oj = organization_json.strip() or "{}"

        persona_patch = json.loads(pj)
        org_patch = json.loads(oj)
        if not isinstance(persona_patch, dict):
            return json.dumps(
                {"ok": False, "error": "persona_json must be a JSON object"},
                indent=2,
                ensure_ascii=False,
            )
        if not isinstance(org_patch, dict):
            return json.dumps(
                {"ok": False, "error": "organization_json must be a JSON object"},
                indent=2,
                ensure_ascii=False,
            )

        bad_p = sorted(set(persona_patch) - _ALLOWED_PLANNER_PERSONA_KEYS)
        if bad_p:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "persona_json has unknown keys: "
                        + ", ".join(repr(k) for k in bad_p)
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        bad_o = sorted(set(org_patch) - _ALLOWED_PLANNER_ORGANIZATION_KEYS)
        if bad_o:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "organization_json has unknown keys: "
                        + ", ".join(repr(k) for k in bad_o)
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )

        if not persona_patch and not org_patch:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "at least one of persona_json or organization_json must be a non-empty object"
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )

        cfg = _load_planner_identity()
        updated: list[str] = []

        if persona_patch:
            pnode = cfg.setdefault("persona", {})
            for key, val in persona_patch.items():
                if val is None:
                    continue
                if not isinstance(val, str):
                    return json.dumps(
                        {
                            "ok": False,
                            "error": f"persona.{key} must be a string (or null to skip)",
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                pnode[key] = val.strip()
                updated.append(f"persona.{key}")

        if org_patch:
            onode = cfg.setdefault("organization", {})
            for key, val in org_patch.items():
                if val is None:
                    continue
                if not isinstance(val, str):
                    return json.dumps(
                        {
                            "ok": False,
                            "error": (
                                "organization.description must be a string (or null to skip)"
                            ),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                onode[key] = val.strip()
                updated.append(f"organization.{key}")

        if not updated:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        "no string fields applied — omit null placeholders or pass at least "
                        "one non-empty persona/organization field"
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )

        persona_path = _persona_path()
        _atomic_write_json(persona_path, cfg)
        logger.info(
            "merge_conversation_planner_identity: wrote %s keys=%s",
            persona_path,
            updated,
        )
        return json.dumps(
            {
                "ok": True,
                "path": str(persona_path),
                "updated_fields": updated,
                "persona": cfg.get("persona", {}),
                "organization": cfg.get("organization", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"ok": False, "error": f"invalid JSON: {exc}"},
            indent=2,
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.exception("merge_conversation_planner_identity failed")
        return json.dumps(
            {"ok": False, "error": str(exc)},
            indent=2,
            ensure_ascii=False,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
