"""Tests for cron.status_report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cron import status_report as sr


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "config").mkdir(parents=True)
    (base / "logs").mkdir(parents=True)
    (base / "config" / "dashboard_routines.json").write_text(
        json.dumps(
            {
                "scheduler_kind": "per_prospect",
                "routines": [],
                "per_prospect": {
                    "connection_sync": {
                        "active": True,
                        "active_window_start": "09:00",
                        "active_window_end": "17:00",
                    },
                    "conversation_plan": {
                        "active": False,
                        "active_window_start": "09:00",
                        "active_window_end": "17:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (base / "logs" / "routine_ticks.jsonl").write_text(
        json.dumps(
            {
                "routine_id": "connection_sync",
                "kind": "sync_sweep",
                "status": "skipped",
                "reason": "outside_window",
                "started_at": "2026-06-25T04:17:27.123506+00:00",
                "finished_at": "2026-06-25T04:17:27.123506+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    return base


def test_build_cron_status_per_prospect(outreach_tmp: Path) -> None:
    now = datetime(2026, 6, 25, 4, 20, tzinfo=timezone.utc)
    status = sr.build_cron_status(now=now)
    assert status["scheduler_kind"] == "per_prospect"
    assert len(status["sweeps"]) == 2
    assert status["sweeps"][0]["id"] == "connection_sync"
    assert status["sweeps"][0]["gate"] == "outside window"
    assert status["sweeps"][1]["active"] is False
    assert status["server"]["auto_start_on_reboot"] is False
    assert "install" in status["notes"][0].lower()


def test_format_sweep_lines_per_prospect(outreach_tmp: Path) -> None:
    now = datetime(2026, 6, 25, 4, 20, tzinfo=timezone.utc)
    text = "\n".join(sr.format_sweep_lines(now=now))
    assert "scheduler  per_prospect" in text
    assert "Connection sync" in text
    assert "Conversation plan" in text
    assert "outside_window" in text


def test_relative_ago() -> None:
    now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
    assert sr._relative_ago("2026-06-25T11:58:00+00:00", now=now) == "2m ago"
    assert sr._relative_ago(None, now=now) == "never"
