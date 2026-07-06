"""
Manual live check for issue #13: opens the messaging thread `send_message`
would pick for a profile, without sending anything, so you can eyeball
whether it landed on the right conversation.

Requires a real Chrome with CDP debugging and an active LinkedIn login:
    make browser          # or: chrome --remote-debugging-port=9222

Usage:
    uv run testing/tools/check_thread_match.py <profile_url> [--search-name "Jay Sato"]
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


async def main(profile_url: str, search_name: str | None, cdp_url: str) -> None:
    async with LinkedInBrowser(mode="attach", cdp_url=cdp_url) as li:
        opened = await li._open_message_ui_from_messaging(
            profile_url, search_name=search_name
        )
        if not opened:
            print("No matching thread found.")
            return
        print("Check the browser window — is this the right person?")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile_url", help="LinkedIn profile URL of the intended recipient")
    parser.add_argument("--search-name", default=None, help="Name to type into inbox search")
    parser.add_argument("--cdp-url", default="http://localhost:9222")
    args = parser.parse_args()
    asyncio.run(main(args.profile_url, args.search_name, args.cdp_url))
