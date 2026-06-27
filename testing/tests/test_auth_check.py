"""Unit tests for LinkedInBrowser.is_logged_in and assert_logged_in."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def browser():
    """LinkedInBrowser instance with a mocked page — no Playwright needed."""
    from outreach.browser import LinkedInBrowser

    li = object.__new__(LinkedInBrowser)
    li._page = MagicMock()
    li._page.is_closed.return_value = False
    li._page.url = "https://www.linkedin.com/feed/"
    li._page.goto = AsyncMock()
    return li


@pytest.mark.asyncio
async def test_is_logged_in_true_when_already_on_linkedin(browser):
    browser._page.url = "https://www.linkedin.com/feed/"
    assert await browser.is_logged_in() is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_on_login_page(browser):
    browser._page.url = "https://www.linkedin.com/login"
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_false_when_on_authwall(browser):
    browser._page.url = "https://www.linkedin.com/authwall"
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_false_when_page_is_none(browser):
    browser._page = None
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_navigates_when_not_on_linkedin(browser):
    browser._page.url = "about:blank"

    async def _nav(*args, **kwargs):
        browser._page.url = "https://www.linkedin.com/feed/"

    browser._page.goto = AsyncMock(side_effect=_nav)
    assert await browser.is_logged_in() is True


@pytest.mark.asyncio
async def test_is_logged_in_false_when_navigation_hits_authwall(browser):
    browser._page.url = "about:blank"

    async def _nav(*args, **kwargs):
        browser._page.url = "https://www.linkedin.com/authwall"

    browser._page.goto = AsyncMock(side_effect=_nav)
    assert await browser.is_logged_in() is False


@pytest.mark.asyncio
async def test_is_logged_in_true_fallback_on_nav_error(browser):
    browser._page.url = "about:blank"
    browser._page.goto = AsyncMock(side_effect=Exception("nav failed"))
    assert await browser.is_logged_in() is True


@pytest.mark.asyncio
async def test_assert_logged_in_raises_when_not_logged_in(browser):
    browser._page.url = "https://www.linkedin.com/login"
    with pytest.raises(RuntimeError, match="run /setup-outreach"):
        await browser.assert_logged_in()


@pytest.mark.asyncio
async def test_assert_logged_in_passes_when_logged_in(browser):
    browser._page.url = "https://www.linkedin.com/feed/"
    await browser.assert_logged_in()  # should not raise
