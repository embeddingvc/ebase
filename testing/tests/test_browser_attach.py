"""Unit tests for LinkedInBrowser._attach's no-open-tabs fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outreach.browser import LinkedInBrowser


def _browser_with_pw(pw_chromium: MagicMock) -> LinkedInBrowser:
    li = object.__new__(LinkedInBrowser)
    li.cdp_url = "http://localhost:9222"
    li._pw = MagicMock()
    li._pw.chromium = pw_chromium
    return li


@pytest.mark.asyncio
async def test_attach_reuses_default_context_when_tabs_open() -> None:
    ctx = MagicMock(pages=[])
    fake_browser = MagicMock(contexts=[ctx])
    pw_chromium = MagicMock()
    pw_chromium.connect_over_cdp = AsyncMock(return_value=fake_browser)
    ctx.new_page = AsyncMock(return_value=MagicMock())

    li = _browser_with_pw(pw_chromium)
    with patch("outreach.browser._open_blank_tab") as open_tab:
        await li._attach()

    open_tab.assert_not_called()
    pw_chromium.connect_over_cdp.assert_awaited_once()
    assert li._ctx is ctx


@pytest.mark.asyncio
async def test_attach_opens_tab_via_cdp_when_no_contexts() -> None:
    ctx = MagicMock(pages=[])
    ctx.new_page = AsyncMock(return_value=MagicMock())
    empty_browser = MagicMock(contexts=[])
    populated_browser = MagicMock(contexts=[ctx])
    pw_chromium = MagicMock()
    pw_chromium.connect_over_cdp = AsyncMock(
        side_effect=[empty_browser, populated_browser]
    )

    li = _browser_with_pw(pw_chromium)
    with patch("outreach.browser._open_blank_tab") as open_tab:
        await li._attach()

    open_tab.assert_called_once_with("http://localhost:9222")
    assert pw_chromium.connect_over_cdp.await_count == 2
    assert li._ctx is ctx
    # The buggy path this replaces — new_context() is unsupported on real Chrome.
    empty_browser.new_context.assert_not_called()
