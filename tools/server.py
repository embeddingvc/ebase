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
    send_connection_request   Send a connection request with an optional note.
    send_message              Send a DM to a 1st-degree connection.
    fetch_chat_history        Read the DM thread for a connection.
    create_new_post           Publish a new post from the home feed.
    reply_to_post             Leave a comment on a LinkedIn post.
    browse_forever            Start a background human-like browsing session.

  [all modes — outreach filesystem; paths are resolved inside the server]
    get_connections           Return outreach/connections.json as JSON text.
    get_prospect              Return outreach/prospects/<id>.json as text.
    get_conversation          Return outreach/conversations/<id>.json as text.
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
        "In mock mode, LinkedIn tools default to the Alex Chen happy_path fixture; "
        "call load_test_case(id, profile_url) to switch scenario (not_interested, ghosted_cold, etc.)."
    ),
)

# ── Background task handle (live mode only) ───────────────────────────────────

_browse_task: asyncio.Task | None = None
_browse_lock = asyncio.Lock()


# ── Mock mode flag ────────────────────────────────────────────────────────────

def _mock_mcp_enabled() -> bool:
    """Return True to run in mock mode (no browser, scripted responses)."""
    return True


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

    Navigates to the given profile, clicks the Message button, types the
    message at human-like speed, and submits it.

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
        success = await li.send_message(profile_url, message)
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

    Opens the same Message flow as send_message and returns message bubbles
    currently in the DOM (older history may require scrolling in the UI).

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
        items = await li.fetch_chat_history(profile_url)
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
        "pending" (default) until LinkedIn accepts; then "accepted".

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

        entry = {
            "prospect_id": resolved_pid,
            "profile_url": profile_url,
            "name": name,
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
            name,
            resolved_pid,
            path,
        )
        return (
            f"ok — saved {name} ({profile_url}) prospect_id={resolved_pid!r} to {path}"
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
