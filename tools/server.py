"""
LinkedIn MCP server.

Exposes LinkedIn browser automation (and a full mock backend for testing)
as MCP tools so Claude — or any MCP host — can drive outreach workflows.

── Modes ─────────────────────────────────────────────────────────────────────

  MOCK MODE  (default; _mock_mcp_enabled() returns True)
    No browser required.  All tool calls are handled by tools/mock.py, which
    simulates complete conversations from connection request to end state.

    Workflow:
      1. send_connection_request(url, note)   — opens the conversation
      2. [conversation-planner skill loop]    — fetch → plan → send, repeat

    Test code configures scenarios via tools/mock.py (e.g. handle_load_test_case);
    those helpers are not exposed as MCP tools.

  LIVE MODE  (_mock_mcp_enabled() returns False)
    Drives a real Chrome browser via Playwright CDP.
    Chrome must be running with --remote-debugging-port=9222 and the user
    must be logged in to LinkedIn manually.

    Quick start:
      make browser          # or launch Chrome with the flags above
      uv run tools/server.py

── Tools ─────────────────────────────────────────────────────────────────────

  [all modes — LinkedIn actions]
    scrape_profile            Scrape a profile → structured JSON.
    parse_profile             Structured multi-page parse (v2 schema; no raw page dump).
    is_first_degree_connection  Check whether a profile is a 1st-degree connection.
      (Used by outreach/skills/sync-pending-connections/SKILL.md with get_connections / save_connection.)
    send_connection_request   Send a connection request with an optional note.
    send_message              Send a DM to a 1st-degree connection.
    fetch_chat_history        Read the DM thread for a connection.
    create_new_post           Publish a new post from the home feed.
    reply_to_post             Leave a comment on a LinkedIn post.
    browse_forever            Start a background human-like browsing session.

  [all modes — outreach filesystem; paths are resolved inside the server]
    Same relative layout as under outreach/; in MOCK MODE data is rooted at
    outreach/mock/ so tests do not write into the live outreach/ tree.

    get_connections           Return .../connections.json as JSON text.
    get_conversation_planner_config Return runtime planner config JSON.
    merge_conversation_planner_identity Merge persona / organization into .../config/persona.json (filesystem only; host LLM summarizes first).
    get_prospect              Return .../prospects/<id>.json as text.
    get_conversation          Return .../conversations/<id>.json as text.
    upsert_conversation_planner_config Write runtime planner config from JSON string.
    upsert_prospect           Write .../prospects/<id>.json from JSON string.
    save_connection           Upsert one row in .../connections.json.
    upsert_conversation       Write .../conversations/<id>.json from JSON string.
    schedule_meeting          Book (mock) or reserve a call after email + time are known.
    append_action_log         Append one JSON line to .../logs/actions.jsonl.
    append_planned_message_log Append one JSON line to planned_messages.jsonl.
    save_outreach_report      Write .../storage/reports/<id>.md.
    remove_pending_queue_entry Remove a prospect from .../queue/pending.json.

── Mock logic ────────────────────────────────────────────────────────────────

  All mock data, state, and handler functions live in tools/mock.py.
  This file only wires them up to the MCP framework.
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

# Make the project root importable (outreach package, tools/mock.py, etc.).
_ROOT = Path(__file__).parent.parent
sys.path.append(str(_ROOT))
# Also ensure the tools/ directory itself is on the path so `import mock` works.
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

from mcp.server.fastmcp import FastMCP

import mock as _mock                    # tools/mock.py
from outreach.browser import LinkedInBrowser

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "linkedin",
    instructions=(
        "Controls a LinkedIn browser session via Playwright CDP. "
    ),
)

# ── Background task handle (live mode only) ───────────────────────────────────

_browse_task: asyncio.Task | None = None
_browse_lock = asyncio.Lock()


# ── Mock mode flag ────────────────────────────────────────────────────────────

def _mock_mcp_enabled() -> bool:
    """Return True to run in mock mode (no browser, scripted responses)."""
    return True


def _outreach_base() -> Path:
    """
    Root directory for outreach filesystem MCP tools.

    Live mode uses ``outreach/``; mock mode uses ``outreach/mock/`` so scripted
    runs do not overwrite operator data under ``outreach/``.
    """
    if _mock_mcp_enabled():
        return _ROOT / "outreach" / "mock"
    return _ROOT / "outreach"


# ═════════════════════════════════════════════════════════════════════════════
# LINKEDIN TOOLS (mock delegates to mock.py; live drives the browser)
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

    In mock mode: returns the prospect from the active session's test case (Alex Chen /
    ``happy_path`` if none was loaded yet).

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
    if _mock_mcp_enabled():
        return await _mock.handle_scrape_profile(profile_url)

    logger.info("scrape_profile called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        profile = await li.scrape_profile(profile_url)
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
    if _mock_mcp_enabled():
        return await _mock.handle_parse_profile(profile_url)

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
    if _mock_mcp_enabled():
        return await _mock.handle_is_first_degree_connection(profile_url)

    logger.info(
        "is_first_degree_connection called  url=%s  cdp=%s", profile_url, cdp_url
    )
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        first = await li.is_first_degree_connection(profile_url)
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

    In mock mode: records the note as operator message 0 and appends the first
    scripted prospect reply.  If the test case has connection_accepted=False,
    the connection stays pending and fetch_chat_history returns an empty thread.

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

    if _mock_mcp_enabled():
        return await _mock.handle_send_connection_request(profile_url, note)

    logger.info(
        "send_connection_request called  url=%s  note_len=%d  cdp=%s",
        profile_url, len(note), cdp_url,
    )
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        success = await li.send_connection_request(profile_url, note=note)
    if success:
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

    In mock mode: appends the operator message to history, then appends the
    next scripted prospect reply (if any).  Silence is simulated when all
    scripted replies are exhausted.

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
    if _mock_mcp_enabled():
        return await _mock.handle_send_message(profile_url, message)

    logger.info("send_message called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        search_name = _lookup_connection_name(profile_url)
        success = await li.send_message(profile_url, message, search_name=search_name)
    if success:
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

    In mock mode: returns the accumulated conversation history for that URL (starts empty
    until ``send_connection_request`` / ``send_message``).  Default session uses the Alex Chen
    ``happy_path`` script unless tests preconfigured another scenario via ``mock.handle_load_test_case``.

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
    if _mock_mcp_enabled():
        return await _mock.handle_fetch_chat_history(profile_url)

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
    if _mock_mcp_enabled():
        return await _mock.handle_create_new_post(content)

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
    if _mock_mcp_enabled():
        return await _mock.handle_reply_to_post(post_url, comment)

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
    if _mock_mcp_enabled():
        return json.dumps(
            {"ok": False, "error": "download_profile_pdf is not supported in mock mode."},
            ensure_ascii=False,
            indent=2,
        )

    filename = f"{uuid.uuid4()}.pdf"
    save_dir = _ROOT / "profiles"

    logger.info("download_profile_pdf called  url=%s  cdp=%s", profile_url, cdp_url)
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        await li.assert_logged_in()
        path = await li.download_profile_pdf(profile_url, save_dir=save_dir, filename=filename)

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

    if _mock_mcp_enabled():
        return await _mock.handle_browse_forever(reaction, cdp_url)

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
# These tools always write under _outreach_base() (outreach/ or outreach/mock/)
# so skills never need to guess paths or run bash scripts.
# ═════════════════════════════════════════════════════════════════════════════

import tempfile
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _planner_config_path() -> Path:
    return _outreach_base() / "config" / "conversation_planner.json"


def _persona_path() -> Path:
    return _outreach_base() / "config" / "persona.json"

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
    Read connections.json from the active outreach data directory (outreach/ or
    outreach/mock/ when mock MCP is enabled). Skills must use this instead of constructing paths.
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


async def _schedule_meeting_live(
    email: str,
    datetime: str,
    prospect_id: str | None = None,
    profile_url: str | None = None,
    cdp_url: str = "http://localhost:9222",
) -> str:
    del email, datetime, prospect_id, profile_url, cdp_url
    return (
        "error: schedule_meeting is not implemented in live mode yet. "
        "Use mock mode for regression, or book manually and set meeting_link "
        "via upsert_conversation."
    )


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

    In mock mode: returns JSON with ``meeting_link`` and ``scheduled_at``, and
    persists ``email`` / ``meeting_link`` on the mock conversation file.

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
    if _mock_mcp_enabled():
        return await _mock.handle_schedule_meeting(
            email=email,
            when=datetime,
            prospect_id=prospect_id,
            profile_url=profile_url,
        )
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
    try:
        data = json.loads(conversation)
        _atomic_write_json(path, data)
        stage = data.get("outreach_stage") if isinstance(data, dict) else None
        if stage in _TERMINAL_CONVERSATION_STAGES:
            _mark_connection_ended(
                prospect_id,
                data.get("linkedin_url") if isinstance(data, dict) else None,
            )
            _sync_prospect_outreach_stage(prospect_id, str(stage))
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
async def remove_pending_queue_entry(prospect_id: str) -> str:
    """
    Remove every queue item with matching ``prospect_id`` from queue/pending.json under the active outreach root.
    No-op if the file is missing or the id is not present.
    """
    path = _outreach_base() / "queue" / "pending.json"
    try:
        if not path.exists():
            return "ok — no pending queue file"
        data = json.loads(path.read_text(encoding="utf-8"))
        queue = data.get("queue")
        if not isinstance(queue, list):
            return "error: pending.json missing a list at key 'queue'"
        before = len(queue)
        data["queue"] = [
            item
            for item in queue
            if not (isinstance(item, dict) and item.get("prospect_id") == prospect_id)
        ]
        if len(data["queue"]) == before:
            return "ok — prospect not in queue (no change)"
        _atomic_write_json(path, data)
        logger.info("remove_pending_queue_entry: removed %s", prospect_id)
        return "ok"
    except Exception as exc:
        logger.exception("remove_pending_queue_entry failed")
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
    if _mock_mcp_enabled():
        logger.warning(
            "LinkedIn MCP server starting in MOCK MODE — "
            "no browser actions are performed; responses use the Alex Chen happy_path fixture by default.\n"
            "  • Outreach filesystem tools read/write under %s (not outreach/).\n"
            "  • send_connection_request(url)   — begin the conversation\n"
            "  • [conversation-planner loop]    — fetch → plan → send\n"
            "  Test scenarios: use tools/mock.py (handle_load_test_case, etc.); not MCP tools.",
            _outreach_base(),
        )
    mcp.run(transport="stdio")
