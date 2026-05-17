"""Tier-0 tests for schedule_meeting MCP tool and mock handler (no Claude CLI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import mock as _mock  # noqa: E402
from outreach.regression_harness import get_server_module  # noqa: E402

PROSPECT_ID = "alex_chen_softeng"
EMAIL = "alexchen336@gmail.com"
WHEN = "2026-05-20T15:00:00Z"


@pytest.fixture
def mock_conversation_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point mock outreach conversations at a temp directory."""
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    conv_path = conv_dir / f"{PROSPECT_ID}.json"
    conv_path.write_text(
        json.dumps(
            {
                "prospect_id": PROSPECT_ID,
                "outreach_stage": "engaged",
                "messages": [],
            }
        ),
        encoding="utf-8",
    )
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    def _base() -> Path:
        return tmp_path

    monkeypatch.setattr(_mock, "_mock_outreach_base", _base)
    return conv_path


@pytest.mark.asyncio
async def test_mock_schedule_meeting_happy(mock_conversation_path: Path) -> None:
    raw = await _mock.handle_schedule_meeting(
        email=EMAIL,
        when=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data = json.loads(raw)
    assert data["status"] == "scheduled"
    assert data["email"] == EMAIL
    assert data["scheduled_at"] == WHEN
    link = data["meeting_link"]
    assert link.startswith("https://mock.calendar.local/")
    assert PROSPECT_ID in link

    raw2 = await _mock.handle_schedule_meeting(
        email=EMAIL,
        when=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data2 = json.loads(raw2)
    assert data2["meeting_link"] == link

    conv = json.loads(mock_conversation_path.read_text(encoding="utf-8"))
    assert conv["email"] == EMAIL
    assert conv["meeting_link"] == link
    assert conv["last_action"] == "confirm_meeting"


@pytest.mark.asyncio
async def test_mock_schedule_invalid_datetime() -> None:
    result = await _mock.handle_schedule_meeting(
        email=EMAIL,
        when="not-a-date",
        prospect_id=PROSPECT_ID,
    )
    assert result.startswith("error:")
    assert "datetime" in result.lower()


@pytest.mark.asyncio
async def test_mock_schedule_missing_context() -> None:
    result = await _mock.handle_schedule_meeting(
        email=EMAIL,
        when=WHEN,
    )
    assert result == "error: prospect context required"


@pytest.mark.asyncio
async def test_server_schedule_meeting_mock_mode(
    mock_conversation_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = get_server_module()
    monkeypatch.setattr(mod, "_mock_mcp_enabled", lambda: True)
    monkeypatch.setattr(mod, "_outreach_base", _mock._mock_outreach_base)

    raw = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data = json.loads(raw)
    assert data["meeting_link"]
    conv = json.loads(mock_conversation_path.read_text(encoding="utf-8"))
    assert conv["meeting_link"] == data["meeting_link"]


@pytest.mark.asyncio
async def test_server_schedule_meeting_live_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = get_server_module()
    monkeypatch.setattr(mod, "_mock_mcp_enabled", lambda: False)
    result = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    assert result.startswith("error:")
    assert "not implemented" in result.lower()
