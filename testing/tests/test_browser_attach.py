"""Unit tests for LinkedInBrowser._attach's no-open-tabs fallback."""

from __future__ import annotations

import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error

from outreach.browser import LinkedInBrowser, _open_blank_tab


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


@pytest.mark.asyncio
async def test_attach_recovers_when_connect_over_cdp_raises_zero_tab_error() -> None:
    """The actual root cause per CHANGELOG: connect_over_cdp itself throws
    with zero open tabs, rather than returning an empty contexts list."""
    ctx = MagicMock(pages=[])
    ctx.new_page = AsyncMock(return_value=MagicMock())
    populated_browser = MagicMock(contexts=[ctx])
    pw_chromium = MagicMock()
    pw_chromium.connect_over_cdp = AsyncMock(
        side_effect=[
            Error("Browser.setDownloadBehavior: Browser context management is not supported"),
            populated_browser,
        ]
    )

    li = _browser_with_pw(pw_chromium)
    with patch("outreach.browser._open_blank_tab") as open_tab:
        await li._attach()

    open_tab.assert_called_once_with("http://localhost:9222")
    assert pw_chromium.connect_over_cdp.await_count == 2
    assert li._ctx is ctx


@pytest.mark.asyncio
async def test_attach_reraises_unrelated_connect_errors() -> None:
    pw_chromium = MagicMock()
    pw_chromium.connect_over_cdp = AsyncMock(side_effect=Error("net::ERR_CONNECTION_REFUSED"))

    li = _browser_with_pw(pw_chromium)
    with patch("outreach.browser._open_blank_tab") as open_tab:
        with pytest.raises(Error, match="ERR_CONNECTION_REFUSED"):
            await li._attach()

    open_tab.assert_not_called()


def test_open_blank_tab_retries_with_get_on_http_error() -> None:
    put_response = MagicMock()
    with patch(
        "urllib.request.urlopen",
        side_effect=[urllib.error.HTTPError("url", 405, "Method Not Allowed", {}, None), put_response],
    ) as urlopen:
        _open_blank_tab("http://localhost:9222")

    assert urlopen.call_count == 2


def test_open_blank_tab_does_not_retry_on_timeout() -> None:
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")
    ) as urlopen:
        with pytest.raises(urllib.error.URLError):
            _open_blank_tab("http://localhost:9222")

    # A bare URLError (timeout, connection refused) might mean the PUT
    # already succeeded server-side — retrying with GET risks opening a
    # second tab, so it must not be attempted.
    urlopen.assert_called_once()
