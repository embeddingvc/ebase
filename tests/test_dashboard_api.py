"""Tests for read-only dashboard API data layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web import dashboard_data as dd  # noqa: E402


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "prospects").mkdir(parents=True)
    (base / "conversations").mkdir(parents=True)
    (base / "queue").mkdir(parents=True)
    (base / "logs").mkdir(parents=True)
    (base / "config").mkdir(parents=True)

    connections = {
        "connections": [
            {
                "prospect_id": "jane_doe",
                "profile_url": "https://www.linkedin.com/in/jane-doe/",
                "name": "Jane Doe",
                "title": "Director",
                "connection_status": "connected",
                "connected_at": "2026-05-01T10:00:00+00:00",
            }
        ]
    }
    (base / "connections.json").write_text(json.dumps(connections), encoding="utf-8")

    conv = {
        "prospect_id": "jane_doe",
        "outreach_stage": "replied",
        "messages": [{"sender": "prospect", "text": "Let's meet", "timestamp": "2026-05-02T10:00:00Z"}],
        "last_action": "send_followup_message",
        "last_action_timestamp": "2026-05-02T09:00:00+00:00",
        "meeting_link": "https://zoom.us/j/123",
        "email": "jane@example.com",
        "ended_reason": "call_scheduled",
    }
    (base / "conversations" / "jane_doe.json").write_text(json.dumps(conv), encoding="utf-8")

    (base / "queue" / "pending.json").write_text(
        json.dumps({"queue": [{"action": "send_followup_message", "prospect_id": "jane_doe", "added_at": "2026-05-03T10:00:00+00:00"}]}),
        encoding="utf-8",
    )
    (base / "queue" / "completed.json").write_text(
        json.dumps(
            {
                "completed": [
                    {
                        "action": "send_connection_request",
                        "prospect_id": "jane_doe",
                        "added_at": "2026-05-01T09:00:00+00:00",
                        "finished_at": "2026-05-01T09:01:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (base / "config" / "conversation_planner.json").write_text(
        json.dumps({"campaign": {"goal": "Test campaign"}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")
    return base


def test_get_connections(outreach_tmp: Path) -> None:
    data = dd.get_connections()
    assert data["total"] == 1
    row = data["connections"][0]
    assert row["name"] == "Jane Doe"
    assert row["title"] == "Director"
    assert row["connection_status"] == "connected"
    assert row["stage_label"] == "Replied"
    assert row["outreach_stage"] == "replied"
    # Connected rows track conversation_plan scheduling.
    sched = row["routine_schedule"]
    assert sched["routine"] == "conversation_plan"
    assert sched["last_run_at"] is None  # no plan_backoff yet
    assert sched["next_run_at"] is None


def test_get_connections_surfaces_pending_sync_backoff(
    outreach_tmp: Path,
) -> None:
    """A pending connection's per-row ``sync_backoff`` becomes the
    last/next-run displayed in the connections table."""
    (outreach_tmp / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "prospect_id": "p1",
                        "profile_url": "https://www.linkedin.com/in/p1/",
                        "name": "Pending One",
                        "connection_status": "pending",
                        "sync_backoff": {
                            "current_interval_minutes": 60,
                            "last_check_at": "2026-05-30T20:00:00+00:00",
                            "next_check_at": "2027-01-01T00:00:00+00:00",
                            "last_result": "no_change",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    data = dd.get_connections()
    row = next(r for r in data["connections"] if r["prospect_id"] == "p1")
    sched = row["routine_schedule"]
    assert sched["routine"] == "connection_sync"
    assert sched["routine_label"] == "Connection sync"
    assert sched["last_run_at"] == "2026-05-30T20:00:00+00:00"
    assert sched["next_run_at"] == "2027-01-01T00:00:00+00:00"
    assert sched["current_interval_minutes"] == 60
    assert sched["last_run_relative"]
    assert sched["next_run_relative"]


def test_get_connections_prefers_connections_json_over_prospect(
    outreach_tmp: Path,
) -> None:
    (outreach_tmp / "prospects" / "jane_doe.json").write_text(
        json.dumps(
            {
                "id": "jane_doe",
                "name": "Wrong Name",
                "title": "Wrong Title",
                "linkedin_url": "https://www.linkedin.com/in/wrong/",
                "connection_status": "pending",
            }
        ),
        encoding="utf-8",
    )
    (outreach_tmp / "conversations" / "orphan.json").write_text(
        json.dumps(
            {
                "prospect_id": "orphan",
                "outreach_stage": "engaged",
                "last_action_timestamp": "2026-05-10T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    data = dd.get_connections()
    assert data["total"] == 1
    assert data["connections"][0]["name"] == "Jane Doe"
    assert data["connections"][0]["title"] == "Director"
    assert all(c["prospect_id"] != "orphan" for c in data["connections"])


def test_get_meetings(outreach_tmp: Path) -> None:
    data = dd.get_meetings()
    assert data["total"] == 1
    assert data["meetings"][0]["email"] == "jane@example.com"
    assert data["meetings"][0]["channel"] == "Zoom"


def test_get_execution_history(outreach_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logs = outreach_tmp / "logs"
    (logs / "routine_runs.jsonl").write_text(
        json.dumps(
            {
                "routine_id": "send_connect",
                "skill": "send-connection-request",
                "status": "success",
                "started_at": "2026-05-03T10:00:00+00:00",
                "finished_at": "2026-05-03T10:00:16+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (logs / "planned_messages.jsonl").write_text(
        json.dumps(
            {
                "prospect_id": "jane_doe",
                "action": "send_followup_message",
                "generated_at": "2026-05-03T11:00:00+00:00",
                "message": "Should not appear",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (outreach_tmp / "config" / "dashboard_routines.json").write_text(
        json.dumps(
            {
                "scheduler_kind": "loop",
                "routines": [
                    {
                        "id": "send_connect",
                        "name": "Send Connection Request",
                        "skill": "send-connection-request",
                        "interval_minutes": 30,
                        "active": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OUTREACH_MOCK", "0")

    data = dd.get_execution_history(limit=10)
    assert data["total"] == 1
    assert data["entries"][0]["routine_name"] == "Send Connection Request"
    assert data["entries"][0]["skill"] == "send-connection-request"
    assert data["entries"][0]["duration_label"] == "16s"
    assert data["stats"]["pending"] == 0


def test_get_health_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dd, "_chrome_running", lambda url=dd.CDP_URL: (False, None))
    health = dd.get_health()
    assert "claude_cli" in health
    assert "cdp_browser" in health
    assert "queue" in health
    assert "worker" not in health
