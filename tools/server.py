"""
LinkedIn MCP server.

Exposes LinkedIn browser automation (and a full mock backend for testing)
as MCP tools so Claude — or any MCP host — can drive outreach workflows.

── Modes ─────────────────────────────────────────────────────────────────────

  MOCK MODE  (default; _mock_mcp_enabled() returns True)
    No browser required.  All tool calls are handled by tools/mock.py, which
    simulates complete conversations from connection request to end state.

    Workflow:
      1. list_test_cases()                    — see available scenarios
      2. load_test_case(id, profile_url)      — reset and configure a session
      3. send_connection_request(url, note)   — opens the conversation
      4. [conversation-planner skill loop]    — fetch → plan → send, repeat
      5. get_mock_state(url)                  — inspect progress at any point

  LIVE MODE  (_mock_mcp_enabled() returns False)
    Drives a real Chrome browser via Playwright CDP.
    Chrome must be running with --remote-debugging-port=9222 and the user
    must be logged in to LinkedIn manually.

    Quick start:
      make browser          # or launch Chrome with the flags above
      uv run tools/server.py

── Tools ─────────────────────────────────────────────────────────────────────

  [mock-only management]
    list_test_cases           List built-in test cases with descriptions.
    load_test_case            Load / reset a test case for a profile URL.
    get_mock_state            Inspect current session state for debugging.

  [all modes — LinkedIn actions]
    scrape_profile            Scrape a profile → structured JSON.
    is_first_degree_connection  Check whether a profile is a 1st-degree connection.
      (Used by outreach/skills/sync-pending-connections/SKILL.md with get_connections / save_connection.)
    send_connection_request   Send a connection request with an optional note.
    send_message              Send a DM to a 1st-degree connection.
    fetch_chat_history        Read the DM thread for a connection.
    create_new_post           Publish a new post from the home feed.
    reply_to_post             Leave a comment on a LinkedIn post.
    browse_forever            Start a background human-like browsing session.

  [all modes — outreach filesystem; paths are resolved inside the server]
    get_connections           Return outreach/connections.json as JSON text.
    get_conversation_planner_config Return runtime planner config JSON.
    get_prospect              Return outreach/prospects/<id>.json as text.
    get_conversation          Return outreach/conversations/<id>.json as text.
    upsert_conversation_planner_config Write runtime planner config from JSON string.
    upsert_prospect           Write outreach/prospects/<id>.json from JSON string.
    save_connection           Upsert one row in outreach/connections.json.
    upsert_conversation       Write outreach/conversations/<id>.json from JSON string.
    append_action_log         Append one JSON line to outreach/logs/actions.jsonl.
    append_planned_message_log Append one JSON line to planned_messages.jsonl.
    save_outreach_report      Write outreach/storage/reports/<id>.md.
    remove_pending_queue_entry Remove a prospect from outreach/queue/pending.json.

── Mock logic ────────────────────────────────────────────────────────────────

  All mock data, state, and handler functions live in tools/mock.py.
  This file only wires them up to the MCP framework.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
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
    return False


# ═════════════════════════════════════════════════════════════════════════════
# MOCK-ONLY MANAGEMENT TOOLS
# ═════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def list_test_cases() -> str:
    """
    [MOCK ONLY] Return all available built-in test cases.

    Each entry includes the test case ID, a plain-English description of the
    scenario, the expected end condition (resume_shared / not_interested /
    timeout), and the number of scripted prospect replies.

    Returns
    -------
    str
        JSON array of test case summaries.
    """
    return await _mock.handle_list_test_cases()


@mcp.tool()
async def load_test_case(
    test_case_id: str,
    profile_url: str,
) -> str:
    """
    [MOCK ONLY] Load (or reset) a predefined test case for a profile URL.

    Optional if you want the default Alex Chen ``happy_path`` scenario (auto-created on first
    LinkedIn tool call for that URL).  Required to use any other scenario.  Calling it again
    on the same URL resets the session from scratch.

    Available test case IDs
    -----------------------
    happy_path      4-turn conversation; prospect shares resume at the end.
    not_interested  Prospect declines politely after the connection note.
    no_reply        Prospect replies once then goes silent (timeout scenario).
    ghosted_cold    Prospect never accepts the connection request.
    eager_referral  Prospect is actively job-seeking; shares resume by turn 2.

    Call list_test_cases() for full descriptions and reply counts.

    Parameters
    ----------
    test_case_id : str
        One of the IDs listed above.
    profile_url : str
        The LinkedIn profile URL to associate with this session.

    Returns
    -------
    str
        Confirmation with a human-readable summary of the loaded scenario.
    """
    return await _mock.handle_load_test_case(test_case_id, profile_url)


@mcp.tool()
async def get_mock_state(profile_url: str) -> str:
    """
    [MOCK ONLY] Inspect the current conversation state for a profile URL.

    Returns session metadata: test case ID, messages sent, history length,
    remaining scripted replies, and a preview of the full conversation so far.

    Parameters
    ----------
    profile_url : str
        The LinkedIn profile URL to inspect.

    Returns
    -------
    str
        JSON object with session state and history preview.
    """
    return await _mock.handle_get_mock_state(profile_url)


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
    ``happy_path`` script unless ``load_test_case`` chose another scenario.

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
# These tools always write to the correct project folder (_ROOT) so skills
# never need to guess paths or run bash scripts.
# ═════════════════════════════════════════════════════════════════════════════

import tempfile
from datetime import datetime, timezone


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_PLANNER_CONFIG_PATH = _ROOT / "outreach" / "config" / "conversation_planner.json"


def _default_conversation_planner_config() -> dict:
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
            "connection_note_char_limit": 300,
            "followup_char_limit": 500,
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

    for key in (
        "persona",
        "organization",
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


def _lookup_connection_name(profile_url: str) -> str | None:
    """
    Read clean name for a profile URL from outreach/connections.json.
    """
    path = _ROOT / "outreach" / "connections.json"
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
    Read outreach/connections.json from the project root (the folder that contains
    tools/server.py). Skills must use this instead of constructing paths.
    """
    path = _ROOT / "outreach" / "connections.json"
    try:
        if not path.exists():
            return json.dumps({"connections": []}, indent=2, ensure_ascii=False) + "\n"
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_connections failed")
        return f"error: {exc}"


@mcp.tool()
async def get_prospect(prospect_id: str) -> str:
    """Read outreach/prospects/<prospect_id>.json as UTF-8 text."""
    path = _ROOT / "outreach" / "prospects" / f"{prospect_id}.json"
    try:
        if not path.exists():
            return f"error: prospect not found: {prospect_id}"
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_prospect failed")
        return f"error: {exc}"


@mcp.tool()
async def get_conversation(prospect_id: str) -> str:
    """Read outreach/conversations/<prospect_id>.json as UTF-8 text."""
    path = _ROOT / "outreach" / "conversations" / f"{prospect_id}.json"
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
    Upsert a connection entry in outreach/connections.json inside the project folder.

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
        Pipeline prospect ID (must match outreach/prospects/<id>.json). If omitted or null, the id is
        taken from an existing row for the same profile_url, else derived from the URL path
        (``/in/handle/`` → ``handle`` with hyphens → underscores). This keeps batch conversation-planner
        runs working after ad-hoc connection sends.
    note_sent : str | None
        The connection note that was sent, or None if no note was included.
    connection_status : str
        "pending" (default) until LinkedIn accepts; then "connected" (see prospect.schema.json).

    Returns
    -------
    str
        Confirmation string on success, or an error description.
    """
    path = _ROOT / "outreach" / "connections.json"
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
        entry = {
            "prospect_id": resolved_pid,
            "profile_url": profile_url,
            "name": clean_name,
            "title": title,
            "connection_status": connection_status,
            "connected_at": _iso_now(),
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


@mcp.tool()
async def upsert_conversation(
    prospect_id: str,
    conversation: str,
) -> str:
    """
    Write (create or overwrite) a conversation JSON file in outreach/conversations/.

    Parameters
    ----------
    prospect_id : str
        The prospect ID — file will be saved as outreach/conversations/<prospect_id>.json.
    conversation : str
        Full JSON string of the conversation object (must match conversation.schema.json).

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    path = _ROOT / "outreach" / "conversations" / f"{prospect_id}.json"
    try:
        data = json.loads(conversation)
        _atomic_write_json(path, data)
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
    Write (create or overwrite) outreach/prospects/<prospect_id>.json.

    Parameters
    ----------
    prospect_id : str
        Filename stem; should match the ``id`` field inside ``prospect`` JSON.
    prospect : str
        Full JSON string of the prospect object (prospect.schema.json).
    """
    path = _ROOT / "outreach" / "prospects" / f"{prospect_id}.json"
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
    Append one JSON entry to outreach/logs/actions.jsonl in the project folder.

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
    path = _ROOT / "outreach" / "logs" / "actions.jsonl"
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
    Append one JSON entry to outreach/logs/planned_messages.jsonl in the project folder.

    Parameters
    ----------
    entry : str
        A JSON object string to append as a single line (PlannedMessage schema).

    Returns
    -------
    str
        "ok" on success, or an error description.
    """
    path = _ROOT / "outreach" / "logs" / "planned_messages.jsonl"
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
    Save an end-of-sequence outreach report to outreach/storage/reports/ in the project folder.

    Parameters
    ----------
    prospect_id : str
        Used as the filename: outreach/storage/reports/<prospect_id>.md
    content : str
        Full markdown content of the report.

    Returns
    -------
    str
        "ok — saved <path>" on success, or an error description.
    """
    path = _ROOT / "outreach" / "storage" / "reports" / f"{prospect_id}.md"
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
    Remove every queue item with matching ``prospect_id`` from outreach/queue/pending.json.
    No-op if the file is missing or the id is not present.
    """
    path = _ROOT / "outreach" / "queue" / "pending.json"
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
    Read outreach/config/conversation_planner.json from the project root.

    Returns the current planner runtime config. Reads from disk on every call so
    manual file edits are reflected immediately.
    """
    try:
        if not _PLANNER_CONFIG_PATH.exists():
            default_cfg = _default_conversation_planner_config()
            _atomic_write_json(_PLANNER_CONFIG_PATH, default_cfg)
            return json.dumps(default_cfg, indent=2, ensure_ascii=False) + "\n"
        return _PLANNER_CONFIG_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception("get_conversation_planner_config failed")
        return f"error: {exc}"


@mcp.tool()
async def upsert_conversation_planner_config(config: str) -> str:
    """
    Write outreach/config/conversation_planner.json from JSON string input.

    Performs lightweight structural validation and writes atomically so runtime
    reads always see a complete file.
    """
    try:
        parsed = json.loads(config)
        validation_error = _validate_conversation_planner_config(parsed)
        if validation_error:
            return f"error: {validation_error}"
        _atomic_write_json(_PLANNER_CONFIG_PATH, parsed)
        logger.info("upsert_conversation_planner_config: wrote %s", _PLANNER_CONFIG_PATH)
        return f"ok — wrote {_PLANNER_CONFIG_PATH}"
    except Exception as exc:
        logger.exception("upsert_conversation_planner_config failed")
        return f"error: {exc}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if _mock_mcp_enabled():
        logger.warning(
            "LinkedIn MCP server starting in MOCK MODE — "
            "no browser actions are performed; responses use the Alex Chen happy_path fixture by default.\n"
            "  • list_test_cases()              — view available scenarios\n"
            "  • load_test_case(id, url)        — optional; switch from default happy_path\n"
            "  • send_connection_request(url)   — begin the conversation\n"
            "  • [conversation-planner loop]    — fetch → plan → send\n"
            "  • get_mock_state(url)            — inspect progress at any time"
        )
    mcp.run(transport="stdio")
