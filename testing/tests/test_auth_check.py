"""Unit tests for LinkedInBrowser.is_logged_in and assert_logged_in."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def browser():
    """LinkedInBrowser instance with mocked page + context — no Playwright needed."""
    from outreach.browser import LinkedInBrowser

    li = object.__new__(LinkedInBrowser)
    li._page = MagicMock()
    li._page.is_closed.return_value = False
    li._page.url = "https://www.linkedin.com/feed/"
    li._ctx = MagicMock()
    li._ctx.cookies = AsyncMock(return_value=[])
    return li


@pytest.mark.asyncio
async def test_is_logged_in_true_when_li_at_cookie_present(browser):
    browser._ctx.cookies.return_value = [{"name": "li_at", "value": "tok123"}]
    assert await browser.is_logged_in() is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_no_cookie_and_login_url(browser):
    browser._ctx.cookies.return_value = []
    browser._page.url = "https://www.linkedin.com/login"
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_false_when_no_cookie_and_authwall(browser):
    browser._ctx.cookies.return_value = []
    browser._page.url = "https://www.linkedin.com/authwall"
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_false_when_page_is_none(browser):
    browser._page = None
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_true_fallback_on_cookies_error(browser):
    browser._ctx.cookies.side_effect = Exception("context crashed")
    assert await browser.is_logged_in() is True


@pytest.mark.asyncio
async def test_assert_logged_in_raises_when_not_logged_in(browser):
    browser._ctx.cookies.return_value = []
    browser._page.url = "https://www.linkedin.com/login"
    with pytest.raises(RuntimeError, match="run /setup-outreach"):
        await browser.assert_logged_in()


@pytest.mark.asyncio
async def test_assert_logged_in_passes_when_logged_in(browser):
    browser._ctx.cookies.return_value = [{"name": "li_at", "value": "tok123"}]
    await browser.assert_logged_in()  # should not raise
