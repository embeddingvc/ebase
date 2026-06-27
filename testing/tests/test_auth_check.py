"""Regression: unauthenticated MCP tool calls return a structured error string."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Load the *real* tools/server.py (not the testing mock at testing/tools/server.py)
_REAL_SERVER_PATH = Path(__file__).resolve().parent.parent.parent / "tools" / "server.py"


def _load_real_server():
    spec = importlib.util.spec_from_file_location("_real_server", _REAL_SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_scrape_profile_returns_auth_error_when_not_logged_in():
    real_server = _load_real_server()

    mock_browser = AsyncMock()
    mock_browser.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_browser.__aexit__ = AsyncMock(return_value=False)
    mock_browser.assert_logged_in = AsyncMock(
        side_effect=RuntimeError(
            "error: not logged in to LinkedIn — run /setup-outreach to restore your browser session"
        )
    )

    with patch.object(real_server, "LinkedInBrowser", return_value=mock_browser), \
         patch.object(real_server, "rate_limit", return_value=None):
        result = await real_server.scrape_profile("https://www.linkedin.com/in/someone/")

    assert "not logged in" in result
    assert "/setup-outreach" in result
