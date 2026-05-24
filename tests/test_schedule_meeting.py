"""Tier-0 tests for schedule_meeting MCP tool and mock handler (no Claude CLI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import mock as _mock  # noqa: E402
import notify as _notify  # noqa: E402
from outreach.regression_harness import get_server_module  # noqa: E402

PROSPECT_ID = "alex_chen_softeng"
EMAIL = "alexchen336@gmail.com"
WHEN = "2026-05-20T15:00:00Z"
PROFILE_URL = "https://www.linkedin.com/in/alex-chen-softeng/"

_SMTP_ENV_KEYS = (
    "OPERATOR_EMAIL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_FROM",
    "SMTP_STARTTLS",
    "SMTP_TIMEOUT_SEC",
    "NOTIFY_DISABLED",
)


def _clear_smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _SMTP_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def live_outreach_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the live server at a temp outreach tree with one seeded connection."""
    mod = get_server_module()
    (tmp_path / "conversations").mkdir()
    (tmp_path / "prospects").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "prospect_id": PROSPECT_ID,
                        "profile_url": PROFILE_URL,
                        "name": "Alex Chen",
                        "title": "ML Engineer",
                        "connection_status": "connected",
                        "connected_at": "2026-05-17T12:00:00+00:00",
                        "note_sent": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_outreach_base", lambda: tmp_path)
    monkeypatch.setattr(mod, "_mock_mcp_enabled", lambda: False)
    _clear_smtp_env(monkeypatch)
    return tmp_path


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


@pytest.fixture
def ended_outreach_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """
    Outreach tree pre-seeded for an end-of-sequence write: an existing
    ``engaged`` conversation, a connection row, and a prospect file. The
    notifier is left unstubbed; tests should monkeypatch it explicitly.
    """
    mod = get_server_module()
    (tmp_path / "conversations").mkdir()
    (tmp_path / "prospects").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "prospect_id": PROSPECT_ID,
                        "profile_url": PROFILE_URL,
                        "name": "Alex Chen",
                        "title": "Engineer",
                        "connection_status": "connected",
                        "connected_at": "2026-05-17T12:00:00+00:00",
                        "note_sent": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "prospects" / f"{PROSPECT_ID}.json").write_text(
        json.dumps({"id": PROSPECT_ID, "outreach_stage": "engaged"}),
        encoding="utf-8",
    )
    (tmp_path / "conversations" / f"{PROSPECT_ID}.json").write_text(
        json.dumps(
            {
                "prospect_id": PROSPECT_ID,
                "outreach_stage": "engaged",
                "messages": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_outreach_base", lambda: tmp_path)
    _clear_smtp_env(monkeypatch)
    return tmp_path


@pytest.mark.asyncio
async def test_upsert_conversation_marks_connection_ended(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal upsert_conversation promotes connections.json to connection_status ended."""
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    prospects_dir = tmp_path / "prospects"
    prospects_dir.mkdir()
    (tmp_path / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "prospect_id": PROSPECT_ID,
                        "profile_url": "https://www.linkedin.com/in/alex-chen-softeng/",
                        "name": "Alex Chen",
                        "title": "Engineer",
                        "connection_status": "connected",
                        "connected_at": "2026-05-17T12:00:00+00:00",
                        "note_sent": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (prospects_dir / f"{PROSPECT_ID}.json").write_text(
        json.dumps({"id": PROSPECT_ID, "outreach_stage": "engaged"}),
        encoding="utf-8",
    )

    mod = get_server_module()
    monkeypatch.setattr(mod, "_outreach_base", lambda: tmp_path)

    conv = {
        "prospect_id": PROSPECT_ID,
        "linkedin_url": "https://www.linkedin.com/in/alex-chen-softeng/",
        "outreach_stage": "ended",
        "ended_reason": "call_scheduled",
        "messages": [],
    }
    result = await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))
    assert result.startswith("ok")

    rows = json.loads((tmp_path / "connections.json").read_text(encoding="utf-8"))
    assert rows["connections"][0]["connection_status"] == "ended"
    assert rows["connections"][0]["connected_at"] == "2026-05-17T12:00:00+00:00"
    prospect = json.loads(
        (prospects_dir / f"{PROSPECT_ID}.json").read_text(encoding="utf-8")
    )
    assert prospect["outreach_stage"] == "ended"


@pytest.mark.asyncio
async def test_upsert_conversation_calls_ended_notifier(
    ended_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first-time transition into 'ended' fires the operator email."""
    mod = get_server_module()
    calls: list[dict] = []

    def _fake_send(**kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(
        mod._notify, "send_conversation_ended_email", _fake_send
    )

    conv = {
        "prospect_id": PROSPECT_ID,
        "linkedin_url": PROFILE_URL,
        "outreach_stage": "ended",
        "ended_reason": "call_scheduled",
        "ended_at": "2026-05-20T15:00:00Z",
        "end_goal": "schedule_meeting",
        "sequence_step": 4,
        "report_path": "outreach/storage/reports/alex_chen_softeng.md",
        "messages": [],
    }
    result = await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))
    assert result.startswith("ok")

    assert len(calls) == 1
    call = calls[0]
    assert call["prospect_id"] == PROSPECT_ID
    assert call["prospect_name"] == "Alex Chen"
    assert call["profile_url"] == PROFILE_URL
    assert call["outreach_stage"] == "ended"
    assert call["ended_reason"] == "call_scheduled"
    assert call["ended_at"] == "2026-05-20T15:00:00Z"
    assert call["sequence_step"] == 4
    assert call["report_path"] == "outreach/storage/reports/alex_chen_softeng.md"
    assert call["end_goal"] == "schedule_meeting"


@pytest.mark.asyncio
async def test_upsert_conversation_notifier_idempotent(
    ended_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-writing an already-terminal conversation must not double-notify."""
    mod = get_server_module()
    calls: list[dict] = []

    def _fake_send(**kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(
        mod._notify, "send_conversation_ended_email", _fake_send
    )

    conv = {
        "prospect_id": PROSPECT_ID,
        "linkedin_url": PROFILE_URL,
        "outreach_stage": "ended",
        "ended_reason": "call_scheduled",
        "messages": [],
    }
    await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))

    conv["report_path"] = "outreach/storage/reports/alex_chen_softeng.md"
    await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_upsert_conversation_no_notify_for_non_terminal(
    ended_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-terminal stages must never fire the ended notifier."""
    mod = get_server_module()
    calls: list[dict] = []

    def _fake_send(**kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(
        mod._notify, "send_conversation_ended_email", _fake_send
    )

    conv = {
        "prospect_id": PROSPECT_ID,
        "linkedin_url": PROFILE_URL,
        "outreach_stage": "replied",
        "messages": [],
    }
    await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))
    assert calls == []


@pytest.mark.asyncio
async def test_upsert_conversation_survives_ended_notifier_error(
    ended_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTP failure on end must not roll back the conversation/connection writes."""
    mod = get_server_module()

    def _boom(**_kwargs):
        return "error: SMTP server down"

    monkeypatch.setattr(
        mod._notify, "send_conversation_ended_email", _boom
    )

    conv = {
        "prospect_id": PROSPECT_ID,
        "linkedin_url": PROFILE_URL,
        "outreach_stage": "dead",
        "ended_reason": "no_response",
        "messages": [],
    }
    result = await mod.upsert_conversation(PROSPECT_ID, json.dumps(conv))
    assert result.startswith("ok")

    rows = json.loads(
        (ended_outreach_root / "connections.json").read_text(encoding="utf-8")
    )
    assert rows["connections"][0]["connection_status"] == "ended"
    prospect = json.loads(
        (ended_outreach_root / "prospects" / f"{PROSPECT_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert prospect["outreach_stage"] == "dead"


@pytest.mark.asyncio
async def test_live_schedule_meeting_writes_conversation(
    live_outreach_root: Path,
) -> None:
    mod = get_server_module()
    raw = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data = json.loads(raw)
    assert data["status"] == "scheduled"
    assert data["prospect_id"] == PROSPECT_ID
    assert data["email"] == EMAIL
    assert data["scheduled_at"] == WHEN
    assert data["meeting_link"] == ""
    assert data["notified"] is False
    assert data["notify_status"] == "skipped"

    conv = json.loads(
        (live_outreach_root / "conversations" / f"{PROSPECT_ID}.json").read_text(
            encoding="utf-8"
        )
    )
    assert conv["email"] == EMAIL
    assert conv["meeting_link"] == ""
    assert conv["last_action"] == "confirm_meeting"
    assert conv["prospect_id"] == PROSPECT_ID

    log_lines = (
        (live_outreach_root / "logs" / "actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert any(json.loads(line)["action"] == "schedule_meeting" for line in log_lines)


@pytest.mark.asyncio
async def test_live_schedule_meeting_resolves_profile_url(
    live_outreach_root: Path,
) -> None:
    mod = get_server_module()
    raw = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        profile_url=PROFILE_URL,
    )
    data = json.loads(raw)
    assert data["prospect_id"] == PROSPECT_ID


@pytest.mark.asyncio
async def test_live_schedule_meeting_invalid_email_and_datetime(
    live_outreach_root: Path,
) -> None:
    mod = get_server_module()
    bad_email = await mod.schedule_meeting(
        email="not-an-email",
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    assert bad_email == "error: invalid email"

    bad_when = await mod.schedule_meeting(
        email=EMAIL,
        datetime="next tuesday",
        prospect_id=PROSPECT_ID,
    )
    assert bad_when == "error: invalid datetime"

    missing_ctx = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
    )
    assert missing_ctx == "error: prospect context required"

    assert not (live_outreach_root / "conversations" / f"{PROSPECT_ID}.json").exists()


@pytest.mark.asyncio
async def test_live_schedule_meeting_calls_notifier(
    live_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = get_server_module()
    calls: list[dict] = []

    def _fake_send(**kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(mod._notify, "send_meeting_scheduled_email", _fake_send)

    raw = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data = json.loads(raw)
    assert data["notified"] is True
    assert data["notify_status"] == "sent"
    assert len(calls) == 1
    assert calls[0]["prospect_id"] == PROSPECT_ID
    assert calls[0]["prospect_name"] == "Alex Chen"
    assert calls[0]["profile_url"] == PROFILE_URL
    assert calls[0]["email"] == EMAIL
    assert calls[0]["scheduled_at"] == WHEN
    assert calls[0]["meeting_link"] == ""


@pytest.mark.asyncio
async def test_live_schedule_meeting_survives_notifier_error(
    live_outreach_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTP failure must not roll back the conversation write."""
    mod = get_server_module()

    def _boom(**_kwargs):
        return "error: SMTP server down"

    monkeypatch.setattr(mod._notify, "send_meeting_scheduled_email", _boom)

    raw = await mod.schedule_meeting(
        email=EMAIL,
        datetime=WHEN,
        prospect_id=PROSPECT_ID,
    )
    data = json.loads(raw)
    assert data["status"] == "scheduled"
    assert data["notified"] is False
    assert data["notify_status"].startswith("error:")
    assert (
        live_outreach_root / "conversations" / f"{PROSPECT_ID}.json"
    ).is_file()


def test_notify_smtp_disabled_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_smtp_env(monkeypatch)
    with patch.object(_notify, "smtplib") as smtp_mock:
        result = _notify.send_meeting_scheduled_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            email=EMAIL,
            scheduled_at=WHEN,
            meeting_link="",
        )
    assert result == "skipped"
    smtp_mock.SMTP.assert_not_called()


def test_notify_smtp_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("NOTIFY_DISABLED", "1")
    with patch.object(_notify, "smtplib") as smtp_mock:
        result = _notify.send_meeting_scheduled_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            email=EMAIL,
            scheduled_at=WHEN,
            meeting_link="",
        )
    assert result == "skipped"
    smtp_mock.SMTP.assert_not_called()


def test_notify_smtp_send_uses_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "ops@example.com")
    monkeypatch.setenv("SMTP_PASS", "hunter2")
    monkeypatch.setenv("SMTP_FROM", "ops@example.com")

    client = MagicMock()
    smtp_factory = MagicMock(return_value=client)
    client.__enter__.return_value = client

    with patch.object(_notify.smtplib, "SMTP", smtp_factory):
        result = _notify.send_meeting_scheduled_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            email=EMAIL,
            scheduled_at=WHEN,
            meeting_link="",
        )

    assert result == "sent"
    smtp_factory.assert_called_once_with("smtp.example.com", 2525, timeout=8.0)
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("ops@example.com", "hunter2")
    client.send_message.assert_called_once()
    sent_msg = client.send_message.call_args.args[0]
    assert sent_msg["To"] == "ops@example.com"
    assert sent_msg["From"] == "ops@example.com"
    assert "Alex Chen" in sent_msg["Subject"]
    assert WHEN in sent_msg["Subject"]
    body = sent_msg.get_content()
    assert EMAIL in body
    assert PROFILE_URL in body


def test_notify_smtp_starttls_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_STARTTLS", "0")

    client = MagicMock()
    client.__enter__.return_value = client
    smtp_factory = MagicMock(return_value=client)

    with patch.object(_notify.smtplib, "SMTP", smtp_factory):
        result = _notify.send_meeting_scheduled_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            email=EMAIL,
            scheduled_at=WHEN,
            meeting_link="",
        )

    assert result == "sent"
    client.starttls.assert_not_called()
    client.login.assert_not_called()
    client.send_message.assert_called_once()


def test_notify_smtp_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import smtplib as real_smtplib

    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    def _raise(*_args, **_kwargs):
        raise real_smtplib.SMTPException("connect refused")

    with patch.object(_notify.smtplib, "SMTP", side_effect=_raise):
        result = _notify.send_meeting_scheduled_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            email=EMAIL,
            scheduled_at=WHEN,
            meeting_link="",
        )
    assert result.startswith("error:")
    assert "connect refused" in result


def test_notify_ended_skipped_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_smtp_env(monkeypatch)
    with patch.object(_notify, "smtplib") as smtp_mock:
        result = _notify.send_conversation_ended_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            outreach_stage="ended",
            ended_reason="call_scheduled",
            ended_at="2026-05-20T15:00:00Z",
        )
    assert result == "skipped"
    smtp_mock.SMTP.assert_not_called()


def test_notify_ended_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("NOTIFY_DISABLED", "1")
    with patch.object(_notify, "smtplib") as smtp_mock:
        result = _notify.send_conversation_ended_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            outreach_stage="dead",
            ended_reason="no_response",
            ended_at="2026-05-20T15:00:00Z",
        )
    assert result == "skipped"
    smtp_mock.SMTP.assert_not_called()


def test_notify_ended_sends_via_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "ops@example.com")
    monkeypatch.setenv("SMTP_PASS", "hunter2")
    monkeypatch.setenv("SMTP_FROM", "ops@example.com")

    client = MagicMock()
    client.__enter__.return_value = client
    smtp_factory = MagicMock(return_value=client)

    with patch.object(_notify.smtplib, "SMTP", smtp_factory):
        result = _notify.send_conversation_ended_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            outreach_stage="ended",
            ended_reason="call_scheduled",
            ended_at="2026-05-20T15:00:00Z",
            sequence_step=4,
            report_path="outreach/storage/reports/alex_chen_softeng.md",
            end_goal="schedule_meeting",
        )

    assert result == "sent"
    smtp_factory.assert_called_once_with("smtp.example.com", 2525, timeout=8.0)
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("ops@example.com", "hunter2")
    client.send_message.assert_called_once()
    sent_msg = client.send_message.call_args.args[0]
    assert sent_msg["To"] == "ops@example.com"
    assert sent_msg["From"] == "ops@example.com"
    assert "Alex Chen" in sent_msg["Subject"]
    assert "closed" in sent_msg["Subject"]
    assert "call_scheduled" in sent_msg["Subject"]
    body = sent_msg.get_content()
    assert "ended" in body
    assert "schedule_meeting" in body
    assert "alex_chen_softeng.md" in body
    assert PROFILE_URL in body


def test_notify_ended_subject_for_dead_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    client = MagicMock()
    client.__enter__.return_value = client
    smtp_factory = MagicMock(return_value=client)

    with patch.object(_notify.smtplib, "SMTP", smtp_factory):
        result = _notify.send_conversation_ended_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            outreach_stage="dead",
            ended_reason="no_response",
            ended_at="2026-05-20T15:00:00Z",
        )

    assert result == "sent"
    sent_msg = client.send_message.call_args.args[0]
    assert "dropped" in sent_msg["Subject"]
    assert "no_response" in sent_msg["Subject"]


def test_notify_ended_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import smtplib as real_smtplib

    _clear_smtp_env(monkeypatch)
    monkeypatch.setenv("OPERATOR_EMAIL", "ops@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")

    def _raise(*_args, **_kwargs):
        raise real_smtplib.SMTPException("connect refused")

    with patch.object(_notify.smtplib, "SMTP", side_effect=_raise):
        result = _notify.send_conversation_ended_email(
            prospect_id=PROSPECT_ID,
            prospect_name="Alex Chen",
            profile_url=PROFILE_URL,
            outreach_stage="ended",
            ended_reason="call_scheduled",
            ended_at="2026-05-20T15:00:00Z",
        )
    assert result.startswith("error:")
    assert "connect refused" in result
