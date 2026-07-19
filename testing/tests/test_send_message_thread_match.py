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

COMPOSE_BTN_SELECTOR = (
    "button.msg-conversations-container__compose-btn, "
    "button[aria-label*='Compose' i]"
)
RECIPIENT_INPUT_SELECTOR = (
    ".msg-connections-typeahead__search-field, "
    "input[placeholder*='Type a name' i]"
)
COMPOSE_OPTIONS_SELECTOR = "li.msg-connections-typeahead__search-result"


def _make_compose_option(name_text: str, *, visible: bool = True) -> MagicMock:
    opt = MagicMock()
    opt.is_visible = AsyncMock(return_value=visible)
    dt = MagicMock()
    dt.inner_text = AsyncMock(return_value=name_text)
    opt.locator = MagicMock(return_value=dt)
    return opt


def _make_row(*, href: str = "", text: str = "", visible: bool = True) -> MagicMock:
    row = MagicMock()
    row.is_visible = AsyncMock(return_value=visible)
    row.get_attribute = AsyncMock(return_value=href)
    row.inner_text = AsyncMock(return_value=text)
    return row


THREAD_LINK_HEADER_SELECTOR = ".msg-thread__link-to-profile .msg-entity-lockup__entity-title"
TITLE_BAR_HEADER_SELECTOR = ".msg-title-bar__title-bar-title h2"
PROFILE_CARD_LINK_SELECTOR = ".msg-s-profile-card .profile-card-one-to-one__profile-link"


def _make_page(
    rows: list[MagicMock],
    *,
    header_name: str | None = None,
    profile_link_href: str | None = None,
    compose_available: bool = False,
    compose_options: list[MagicMock] | None = None,
    profile_card_href: str | None = None,
) -> MagicMock:
    page = MagicMock()
    page.url = "https://www.linkedin.com/messaging/"
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.go_back = AsyncMock()
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
    page.profile_link = profile_link  # test-only handle, see _clicking_resolves_to()

    compose_btn = MagicMock()
    compose_btn.count = AsyncMock(return_value=1 if compose_available else 0)
    page.compose_btn = compose_btn  # test-only handle, for click assertions

    recipient_input = MagicMock()
    page.recipient_input = recipient_input

    options = compose_options or []
    options_locator = MagicMock()
    options_locator.count = AsyncMock(return_value=len(options))
    options_locator.nth = MagicMock(side_effect=lambda i: options[i])

    profile_card_link = MagicMock()
    profile_card_link.count = AsyncMock(return_value=1 if profile_card_href is not None else 0)
    profile_card_link.get_attribute = AsyncMock(return_value=profile_card_href or "")
    profile_card_link.inner_text = AsyncMock(return_value=header_name or "")

    def locator_side_effect(sel: str):
        if sel == SEARCH_ROWS_SELECTOR:
            return rows_locator
        if sel == "input[placeholder*='Search messages' i]":
            m = MagicMock()
            m.first = search_box
            return m
        if sel == PROFILE_CARD_LINK_SELECTOR:
            return MagicMock(first=profile_card_link)
        if sel == THREAD_LINK_HEADER_SELECTOR:
            return MagicMock(first=header)
        if sel == TITLE_BAR_HEADER_SELECTOR:
            return MagicMock(first=MagicMock(count=AsyncMock(return_value=0)))
        if sel == ".msg-thread__link-to-profile":
            return MagicMock(first=profile_link)
        if sel == COMPOSE_BTN_SELECTOR:
            return MagicMock(first=compose_btn)
        if sel == RECIPIENT_INPUT_SELECTOR:
            return MagicMock(first=recipient_input)
        if sel == COMPOSE_OPTIONS_SELECTOR:
            return options_locator
        m = MagicMock()
        m.count = AsyncMock(return_value=0)
        m.first = MagicMock()
        m.first.count = AsyncMock(return_value=0)
        return m

    page.locator = MagicMock(side_effect=locator_side_effect)
    page.get_by_role = MagicMock(
        return_value=MagicMock(first=MagicMock(count=AsyncMock(return_value=0)))
    )
    return page


def _browser(page: MagicMock) -> LinkedInBrowser:
    li = object.__new__(LinkedInBrowser)
    li._page = page
    li._ctx = MagicMock()
    return li


def _clicking_resolves_to(page: MagicMock, resolved_url: str):
    """Simulate LinkedIn's client-side router: clicking the profile link
    changes ``page.url`` to the vanity URL, like a real click would."""

    async def side_effect(clicked_page, target):
        if target is page.profile_link:
            clicked_page.url = resolved_url

    return side_effect


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
    """Same name, but clicking the thread's profile link lands on a
    different vanity URL — that's the ground truth over the (possibly
    duplicate) displayed name."""
    row = _make_row(text="Jay Sato, 1st")
    page = _make_page(
        [row],
        header_name="Jay Sato",
        profile_link_href="https://www.linkedin.com/in/ACoAAdifferentperson",
    )
    li = _browser(page)

    with (
        patch(
            "outreach.browser._human_click",
            new=AsyncMock(
                side_effect=_clicking_resolves_to(
                    page, "https://www.linkedin.com/in/a-different-jay-sato/"
                )
            ),
        ),
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
    li = _browser(page)

    with (
        patch(
            "outreach.browser._human_click",
            new=AsyncMock(
                side_effect=_clicking_resolves_to(
                    page, "https://www.linkedin.com/in/jay-sato-263a85270/"
                )
            ),
        ),
        patch("outreach.browser._human_pause", new=AsyncMock()),
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok


@pytest.mark.asyncio
async def test_no_thread_falls_back_to_compose_and_matches_recipient():
    """A connection accepted without a note has no thread anywhere in the
    inbox — must fall back to 'Compose a new message' and its typeahead.

    The resulting draft (.../messaging/thread/new/) has no persisted thread
    id, so its title bar just says "New message" — verification must use the
    profile card's direct vanity-slug link instead (no click-resolve needed)."""
    match = _make_compose_option("Jay Sato • 1st")
    page = _make_page(
        [],
        header_name="Jay Sato",
        profile_card_href="https://www.linkedin.com/in/jay-sato-263a85270/",
        compose_available=True,
        compose_options=[match],
    )
    li = _browser(page)

    with (
        patch("outreach.browser._human_click", new=AsyncMock()) as click,
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch(
            "outreach.browser.expect",
            new=MagicMock(return_value=MagicMock(to_be_visible=AsyncMock())),
        ),
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok
    click.assert_any_await(li._page, page.compose_btn)
    click.assert_any_await(li._page, match)


@pytest.mark.asyncio
async def test_compose_fallback_wrong_candidate_caught_by_profile_check():
    """Typeahead has two same-name candidates (a real LinkedIn scenario);
    the name-only match can pick the wrong one, but the profile card's
    resolved vanity URL must still catch it before send."""
    wrong_match = _make_compose_option("Andrew Barreto • 2nd")
    page = _make_page(
        [],
        header_name="Andrew Barreto",
        profile_card_href="https://www.linkedin.com/in/a-different-andrew-barreto/",
        compose_available=True,
        compose_options=[wrong_match],
    )
    li = _browser(page)

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch(
            "outreach.browser.expect",
            new=MagicMock(return_value=MagicMock(to_be_visible=AsyncMock())),
        ),
        patch("outreach.browser.logger") as logger,
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/andrew-barreto-123abc/"
        )

    assert not ok
    assert logger.warning.called


@pytest.mark.asyncio
async def test_no_thread_and_no_compose_button_returns_false():
    page = _make_page([], compose_available=False)
    li = _browser(page)

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
async def test_retries_when_freshly_accepted_connection_not_yet_indexed():
    """Regression test for issue #24: a connection accepted moments ago can
    be briefly missing from LinkedIn's messaging search/typeahead. The first
    attempt finds no thread and no compose candidate; a retry (after a
    reload) finds the thread and must succeed."""
    attempt = {"n": 0}

    def locator_side_effect(sel: str):
        if sel == SEARCH_ROWS_SELECTOR:
            rows = [] if attempt["n"] == 0 else [_make_row(text="Jay Sato, 1st")]
            loc = MagicMock()
            loc.count = AsyncMock(return_value=len(rows))
            loc.nth = MagicMock(side_effect=lambda i: rows[i])
            return loc
        if sel == "input[placeholder*='Search messages' i]":
            search_box = MagicMock()
            search_box.count = AsyncMock(return_value=1)
            search_box.is_visible = AsyncMock(return_value=True)
            search_box.fill = AsyncMock()
            return MagicMock(first=search_box)
        m = MagicMock()
        m.count = AsyncMock(return_value=0)
        m.first = MagicMock(count=AsyncMock(return_value=0))
        return m

    async def goto_side_effect(*_args, **_kwargs):
        attempt["n"] += 1

    page = MagicMock()
    page.url = "https://www.linkedin.com/messaging/"
    page.goto = AsyncMock(side_effect=goto_side_effect)
    page.wait_for_selector = AsyncMock()
    page.keyboard = MagicMock(type=AsyncMock(), press=AsyncMock())
    page.locator = MagicMock(side_effect=locator_side_effect)
    page.get_by_role = MagicMock(
        return_value=MagicMock(first=MagicMock(count=AsyncMock(return_value=0)))
    )
    li = _browser(page)

    with (
        patch("outreach.browser._human_click", new=AsyncMock()),
        patch("outreach.browser._human_pause", new=AsyncMock()),
        patch("outreach.browser.logger") as logger,
    ):
        ok = await li._open_message_ui_from_messaging(
            "https://www.linkedin.com/in/jay-sato-263a85270/"
        )

    assert ok
    assert page.goto.await_count == 1
    assert any("retrying" in str(c).lower() for c in logger.info.call_args_list)
