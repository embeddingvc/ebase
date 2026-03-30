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

  browse_forever   Start a background human-like browsing session.

── Adding more tools ──────────────────────────────────────────────────────────

  This file intentionally wraps only browse_forever for now.
  Add new @mcp.tool() functions here as additional LinkedIn actions are needed.
"""

from __future__ import annotations

import asyncio
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
