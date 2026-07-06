"""
Manual live tool: sends a real DM to an existing 1st-degree connection via
LinkedInBrowser.send_message (same thread-match + verification logic used
in production, see check_thread_match.py for a no-send dry run of that).

Requires a real Chrome with CDP debugging and an active LinkedIn login:
    make browser          # or: chrome --remote-debugging-port=9222

Usage:
    uv run testing/tools/send_message.py <profile_url> "<message text>" [--search-name "Jay Sato"]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))  # repo root

from outreach.browser import LinkedInBrowser

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def main(profile_url: str, message: str, search_name: str | None, cdp_url: str) -> None:
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        sent = await li.send_message(profile_url, message, search_name=search_name)
        print("Sent." if sent else "Failed to send — see warnings above.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_url", help="LinkedIn profile URL of the recipient")
    parser.add_argument("message", help="Message text to send")
    parser.add_argument("--search-name", default=None, help="Name to type into inbox search")
    parser.add_argument("--cdp-url", default="http://localhost:9222")
    args = parser.parse_args()
    asyncio.run(main(args.profile_url, args.message, args.search_name, args.cdp_url))
