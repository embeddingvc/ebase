"""Unit tests for the issue #13 fix: search results must be hint-matched,
not just the first visible row, before send_message/fetch_chat_history act
on a thread."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from outreach.browser import LinkedInBrowser

SEARCH_ROWS_SELECTOR = (
    "a[href*='/messaging/thread/'], "
    ".msg-conversation-listitem a, "
    ".msg-conversation-listitem div.msg-conversation-listitem__link, "
    "li.msg-conversation-listitem, "
    "[data-view-name*='search'] a[href*='/messaging/']"
)


def _make_row(*, href: str = "", text: str = "", visible: bool = True) -> MagicMock:
    row = MagicMock()
    row.is_visible = AsyncMock(return_value=visible)
    row.get_attribute = AsyncMock(return_value=href)
    row.inner_text = AsyncMock(return_value=text)
    return row


HEADER_SELECTOR = (
    ".msg-thread__link-to-profile .msg-entity-lockup__entity-title, "
    ".msg-title-bar__title-bar-title h2"
)


def _make_page(
    rows: list[MagicMock],
    *,
    header_name: str | None = None,
    profile_link_href: str | None = None,
) -> MagicMock:
    page = MagicMock()
    page.url = "https://www.linkedin.com/messaging/"
    page.wait_for_selector = AsyncMock()
    page.keyboard = MagicMock(type=AsyncMock(), press=AsyncMock())

    search_box = MagicMock()
    search_box.count = AsyncMock(return_value=1)
    search_box.is_visible = AsyncMock(return_value=True)
    search_box.fill = AsyncMock()

    rows_locator = MagicMock()
    rows_locator.count = AsyncMock(return_value=len(rows))
    rows_locator.nth = MagicMock(side_effect=lambda i: rows[i])

    header = MagicMock()
    header.count = AsyncMock(return_value=1 if header_name is not None else 0)
    header.inner_text = AsyncMock(return_value=header_name or "")

    profile_link = MagicMock()
    profile_link.count = AsyncMock(return_value=1 if profile_link_href is not None else 0)
    profile_link.get_attribute = AsyncMock(return_value=profile_link_href or "")

    def locator_side_effect(sel: str):
        if sel == SEARCH_ROWS_SELECTOR:
            return rows_locator
        if sel == "input[placeholder*='Search messages' i]":
            m = MagicMock()
            m.first = search_box
            return m
        if sel == HEADER_SELECTOR:
            return MagicMock(first=header)
        if sel == ".msg-thread__link-to-profile":
            return MagicMock(first=profile_link)
        m = MagicMock()
        m.first = MagicMock()
        m.first.count = AsyncMock(return_value=0)
        return m

    page.locator = MagicMock(side_effect=locator_side_effect)
    page.get_by_role = MagicMock(
        return_value=MagicMock(first=MagicMock(count=AsyncMock(return_value=0)))
    )
    return page


def _browser(page: MagicMock, *, resolved_url: str | None = None) -> LinkedInBrowser:
    li = object.__new__(LinkedInBrowser)
    li._page = page
    li._ctx = MagicMock()
    li._ctx.request.get = AsyncMock(return_value=MagicMock(url=resolved_url or ""))
    return li


@pytest.mark.asyncio
async def test_search_results_prefer_hint_match_over_first_visible():
    wrong_first = _make_row(text="Unrelated Person, 2nd")
    correct_match = _make_row(text="Jay Sato, 1st")
    li = _browser(_make_page([wrong_first, correct_match]))

    with (
        patch("outreach.browser._human_click", new=AsyncMock()) as click,
        patch("outreach.browser._human_pause", new=AsyncMock()),
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok
    click.assert_awaited_with(li._page, correct_match)


@pytest.mark.asyncio
async def test_search_results_fall_back_to_first_visible_with_warning():
    first = _make_row(text="No relation here")
    second = _make_row(text="Also unrelated")
    li = _browser(_make_page([first, second]))

    with (
        patch("outreach.browser._human_click", new=AsyncMock()) as click,
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch("outreach.browser.logger") as logger,
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok
    click.assert_awaited_with(li._page, first)
    assert logger.warning.called


@pytest.mark.asyncio
async def test_thread_header_mismatch_rejects_wrong_thread():
    """Row text matched, but the opened thread's own title bar says otherwise
    (e.g. a stale/misleading list row) — must not be treated as success."""
    row = _make_row(text="Jay Sato, 1st")
    li = _browser(_make_page([row], header_name="Andrew Barreto"))

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch("outreach.browser.logger") as logger,
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert not ok
    assert logger.warning.called


@pytest.mark.asyncio
async def test_thread_header_match_confirms_open():
    row = _make_row(text="Jay Sato, 1st")
    li = _browser(_make_page([row], header_name="Jay Sato"))

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok


@pytest.mark.asyncio
async def test_thread_profile_url_mismatch_rejects_even_with_matching_name():
    """Same name, but the thread's profile link redirects somewhere else —
    the resolved URL is the ground truth over the (possibly duplicate) name."""
    row = _make_row(text="Jay Sato, 1st")
    page = _make_page(
        [row],
        header_name="Jay Sato",
        profile_link_href="https://www.linkedin.com/in/ACoAAdifferentperson",
    )
    li = _browser(page, resolved_url="https://www.linkedin.com/in/a-different-jay-sato/")

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch("outreach.browser.logger") as logger,
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert not ok
    assert logger.warning.called


@pytest.mark.asyncio
async def test_thread_profile_url_match_confirms_open():
    row = _make_row(text="Jay Sato, 1st")
    page = _make_page(
        [row],
        header_name="Jay Sato",
        profile_link_href="https://www.linkedin.com/in/ACoAAjaysato",
    )
    li = _browser(
        page, resolved_url="https://www.linkedin.com/in/jay-sato-263a85270/"
    )

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok
