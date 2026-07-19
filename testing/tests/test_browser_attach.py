"""Unit tests for LinkedInBrowser._attach's no-open-tabs fallback, plus the
cross-process tab lock and same-profile guard added for issue #22."""

from __future__ import annotations

import asyncio
import urllib.error
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error

import outreach.browser as browser_mod
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
async def test_attach_raises_clear_error_when_still_no_contexts() -> None:
    empty_browser = MagicMock(contexts=[])
    pw_chromium = MagicMock()
    pw_chromium.connect_over_cdp = AsyncMock(return_value=empty_browser)

    li = _browser_with_pw(pw_chromium)
    with patch("outreach.browser._open_blank_tab") as open_tab:
        with pytest.raises(RuntimeError, match="no browser context"):
            await li._attach()

    open_tab.assert_called_once_with("http://localhost:9222")


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


# ── Cross-process tab lock (issue #22: shared-tab race) ────────────────────────


@pytest.mark.asyncio
async def test_tab_lock_serializes_concurrent_sessions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(browser_mod, "_TAB_LOCK_PATH", tmp_path / "browser.lock")

    li1 = object.__new__(LinkedInBrowser)
    li1._lock_fh = None
    li2 = object.__new__(LinkedInBrowser)
    li2._lock_fh = None

    await li1._acquire_tab_lock()
    try:
        task2 = asyncio.create_task(li2._acquire_tab_lock())
        await asyncio.sleep(0.2)
        assert not task2.done(), "second session must block while the first holds the lock"
    finally:
        await li1._release_tab_lock()

    await asyncio.wait_for(task2, timeout=2)
    assert li2._lock_fh is not None
    await li2._release_tab_lock()


def _browser_with_page_url(url: str) -> LinkedInBrowser:
    li = object.__new__(LinkedInBrowser)
    li._page = MagicMock(url=url)
    return li


def test_tab_left_for_other_profile_false_for_same_profile() -> None:
    li = _browser_with_page_url("https://www.linkedin.com/in/daksh_p_37808729a/")
    assert not li._tab_left_for_other_profile(
        "https://www.linkedin.com/in/daksh_p_37808729a/"
    )


def test_tab_left_for_other_profile_true_for_different_profile() -> None:
    li = _browser_with_page_url("https://www.linkedin.com/in/sohan-patra/")
    assert li._tab_left_for_other_profile(
        "https://www.linkedin.com/in/daksh_p_37808729a/"
    )


def test_tab_left_for_other_profile_tolerates_non_in_routes() -> None:
    # The invite flow can legitimately hop through routes like
    # /preload/custom-invite/ for the *correct* profile — must not false-positive.
    li = _browser_with_page_url("https://www.linkedin.com/preload/custom-invite/?id=1")
    assert not li._tab_left_for_other_profile(
        "https://www.linkedin.com/in/daksh_p_37808729a/"
    )
