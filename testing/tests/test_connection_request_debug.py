"""Unit tests for the connection-request forensic debug dump (issue #22)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from outreach.browser import _dump_connection_request_debug, _human_type


@pytest.mark.asyncio
async def test_dump_connection_request_debug_writes_html_and_json(tmp_path) -> None:
    page = MagicMock(url="https://www.linkedin.com/in/daksh_p_37808729a/")
    page.content = AsyncMock(return_value="<html>profile page</html>")

    await _dump_connection_request_debug(
        page,
        "20260716T000000000000_daksh",
        "before_connect_click",
        {"profile_url": page.url, "note": "hi"},
        dir_path=tmp_path,
    )

    html_path = tmp_path / "20260716T000000000000_daksh_before_connect_click.html"
    json_path = tmp_path / "20260716T000000000000_daksh_before_connect_click.json"
    assert html_path.read_text(encoding="utf-8") == "<html>profile page</html>"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["profile_url"] == page.url
    assert payload["tag"] == "before_connect_click"
    assert payload["page_url"] == page.url


@pytest.mark.asyncio
async def test_dump_connection_request_debug_captures_extra_html(tmp_path) -> None:
    page = MagicMock(url="https://www.linkedin.com/in/daksh_p_37808729a/")
    page.content = AsyncMock(return_value="<html></html>")
    dialog = MagicMock()
    dialog.evaluate = AsyncMock(return_value="<div>invite dialog</div>")

    await _dump_connection_request_debug(
        page,
        "run1",
        "before_note_type",
        {"profile_url": page.url},
        dir_path=tmp_path,
        extra_html={"dialog": dialog},
    )

    dialog_path = tmp_path / "run1_before_note_type_dialog.html"
    assert dialog_path.read_text(encoding="utf-8") == "<div>invite dialog</div>"


@pytest.mark.asyncio
async def test_human_type_accepts_scoped_locator_instead_of_page_selector() -> None:
    """
    The invite-note field must be typed into via a Locator scoped to the
    confirmed dialog, not a page-global selector — LinkedIn reuses
    textarea[name='message'] for chat-compose boxes too, so a bare
    page.click(selector) could land in the wrong one.
    """
    page = MagicMock()
    page.click = AsyncMock()
    page.keyboard.type = AsyncMock()
    scoped_field = MagicMock()
    scoped_field.click = AsyncMock()

    await _human_type(page, scoped_field, "hi")

    scoped_field.click.assert_awaited_once()
    page.click.assert_not_called()
