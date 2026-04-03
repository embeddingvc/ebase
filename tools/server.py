"""
LinkedIn MCP server.

Exposes LinkedIn browser automation as MCP tools so Claude (or any MCP host)
can drive the browser directly.

── Quick start ────────────────────────────────────────────────────────────────

  1. Make sure Chrome is running with remote-debugging enabled:

         make browser
     or:
         open -a "Google Chrome" --args \\
           --remote-debugging-port=9222 \\
           --user-data-dir=$HOME/.linkedin-chrome-profile \\
           --no-first-run

  2. Log in to LinkedIn manually in that window (one-time).

  3. Start the MCP server:

         uv run mcp/server.py

  4. Register with Claude Desktop by adding to ~/Library/Application Support/Claude/claude_desktop_config.json:

         {
           "mcpServers": {
             "linkedin": {
               "command": "uv",
               "args": ["run", "mcp/server.py"],
               "cwd": "/path/to/LinkedIn Outreach"
             }
           }
         }

── Tools exposed ──────────────────────────────────────────────────────────────

  browse_forever            Start a background human-like browsing session.
  scrape_profile            Scrape a LinkedIn profile URL and return structured data.
  send_connection_request   Send a connection request, with an optional note.
  send_message              Send a direct message to a 1st-degree connection.
  reply_to_post             Leave a comment (reply) on a LinkedIn post.

── Adding more tools ──────────────────────────────────────────────────────────

  Add new @mcp.tool() functions here as additional LinkedIn actions are needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Append the project root so the installed `mcp` PyPI package takes priority
# over the local mcp/ directory, while still making `outreach` importable.
sys.path.append(str(Path(__file__).parent.parent))

# ── Logging setup ─────────────────────────────────────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
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

from outreach.browser import LinkedInBrowser

# ── MCP server instance ───────────────────────────────────────────────────────

mcp = FastMCP(
    "linkedin",
    instructions=(
        "Controls a LinkedIn browser session via Playwright CDP. "
        "Chrome must already be running with --remote-debugging-port=9222 "
        "and the user must be logged in to LinkedIn manually."
    ),
)

# ── Internal state ────────────────────────────────────────────────────────────

# Holds the running browse_forever background task (at most one at a time).
_browse_task: asyncio.Task | None = None
_browse_lock = asyncio.Lock()


# ── Tools ─────────────────────────────────────────────────────────────────────

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

    The browsing connects to an already-running Chrome via CDP so LinkedIn sees
    a warm, authenticated session — no login flow is triggered.

    Parameters
    ----------
    reaction
        Reaction type applied randomly while scrolling the feed (~20 % of posts).
        One of: Like, Celebrate, Support, Funny, Love, Insightful.
        Defaults to "Like".
    cdp_url
        Chrome DevTools Protocol endpoint to attach to.
        Defaults to "http://localhost:9222".

    Returns
    -------
    str
        Confirmation that the session was started, or a notice that one is
        already running.
    """
    global _browse_task

    async with _browse_lock:
        # Guard against starting a second session while one is live.
        if _browse_task is not None and not _browse_task.done():
            logger.warning("browse_forever called but a session is already running")
            return (
                "A browse_forever session is already running. "
                "It will stop automatically when the server process exits "
                "or receives SIGINT/SIGTERM."
            )

        async def _run() -> None:
            logger.info(
                "browse_forever session started  cdp=%s  reaction=%s",
                cdp_url,
                reaction,
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
        "browse_forever task created  cdp=%s  reaction=%s",
        cdp_url,
        reaction,
    )
    return (
        f"browse_forever started — "
        f"reaction={reaction!r}, "
        f"cdp={cdp_url}. "
        "The session runs in the background. "
        "It will stop when the MCP server process exits."
    )


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
    profile_url
        Full LinkedIn profile URL, e.g. "https://www.linkedin.com/in/username/".
    cdp_url
        Chrome DevTools Protocol endpoint of the already-running Chrome instance.
        Defaults to "http://localhost:9222".

    Returns
    -------
    str
        JSON-encoded dict with keys:
          linkedin_url, name, title, location, connection_degree,
          about, recent_posts, scraped_at.
    """
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

    Parameters
    ----------
    profile_url
        Full LinkedIn profile URL, e.g. "https://www.linkedin.com/in/username/".
    note
        Personalised connection note (LinkedIn limit: 300 chars).
        Pass an empty string to send without a note.
    cdp_url
        Chrome DevTools Protocol endpoint of the already-running Chrome instance.
        Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description if the request could not be sent.
    """
    if len(note) > 300:
        return f"Note too long: {len(note)} chars (LinkedIn limit: 300). Please shorten and retry."

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
        "The Connect button was not found — the profile may already be a connection, "
        "have a pending request, or the button is hidden behind the More menu."
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

    Parameters
    ----------
    profile_url
        Full LinkedIn profile URL, e.g. "https://www.linkedin.com/in/username/".
    message
        Message body to send (LinkedIn limit: ~8 000 chars).
    cdp_url
        Chrome DevTools Protocol endpoint of the already-running Chrome instance.
        Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description if the message could not be sent.
    """
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
    post_url
        Direct URL of the LinkedIn post or activity item.
    comment
        Comment text to post.
    cdp_url
        Chrome DevTools Protocol endpoint of the already-running Chrome instance.
        Defaults to "http://localhost:9222".

    Returns
    -------
    str
        "ok" on success, or an error description if the comment could not be posted.
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
