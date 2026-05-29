"""Tests for the deterministic connection-sync sweep (no LLM)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web import connection_sync_sweep as css  # noqa: E402
from web.routine_backoff import SYNC_DEFAULT  # noqa: E402


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "logs").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")
    return base


def _write_connections(base: Path, rows: list[dict[str, Any]]) -> None:
    (base / "connections.json").write_text(
        json.dumps({"connections": rows}), encoding="utf-8"
    )


def _default_rcfg(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "active": True,
        "active_window_start": None,
        "active_window_end": None,
        "backoff": {
            "initial_minutes": SYNC_DEFAULT.initial_minutes,
            "multiplier": SYNC_DEFAULT.multiplier,
            "max_minutes": SYNC_DEFAULT.max_minutes,
            "error_jitter": False,  # deterministic for tests
        },
    }
    cfg.update(overrides)
    return cfg


def test_sync_sweep_promotes_accepted_invite(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "name": "Pending One",
                "connection_status": "pending",
            }
        ],
    )

    async def probe(_url: str) -> bool:
        return True

    result = css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    assert result.checked == 1
    assert len(result.promoted) == 1
    assert result.still_pending == 0

    on_disk = json.loads((outreach_tmp / "connections.json").read_text())
    row = on_disk["connections"][0]
    assert row["connection_status"] == "connected"
    assert "sync_backoff" not in row


def test_sync_sweep_bumps_backoff_when_still_pending(
    outreach_tmp: Path,
) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "name": "Pending One",
                "connection_status": "pending",
            }
        ],
    )

    async def probe(_url: str) -> bool:
        return False

    result = css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    assert result.checked == 1
    assert result.still_pending == 1
    assert not result.promoted

    row = json.loads((outreach_tmp / "connections.json").read_text())["connections"][0]
    assert row["connection_status"] == "pending"
    assert "sync_backoff" in row
    # First bump: 30 * 1.5 = 45 minutes (no jitter under our test policy).
    assert row["sync_backoff"]["current_interval_minutes"] == 45


def test_sync_sweep_respects_existing_next_check(outreach_tmp: Path) -> None:
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "name": "Pending One",
                "connection_status": "pending",
                "sync_backoff": {
                    "current_interval_minutes": 120,
                    "next_check_at": future_iso,
                    "last_result": "no_change",
                },
            }
        ],
    )

    calls: list[str] = []

    async def probe(url: str) -> bool:
        calls.append(url)
        return False

    result = css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    assert result.checked == 0
    assert result.skipped_not_due == 1
    assert calls == []


def test_sync_sweep_records_tool_error(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "name": "Pending One",
                "connection_status": "pending",
            }
        ],
    )

    async def probe(_url: str) -> str:
        return "error: browser disconnected"

    result = css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    assert result.checked == 1
    assert len(result.errors) == 1
    row = json.loads((outreach_tmp / "connections.json").read_text())["connections"][0]
    # Row stays pending and gains a backoff record with the error message.
    assert row["connection_status"] == "pending"
    assert row["sync_backoff"]["last_result"] == "tool_error"
    assert "browser disconnected" in row["sync_backoff"]["last_error"]


def test_sync_sweep_bails_on_rate_limit(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "name": "Pending One",
                "connection_status": "pending",
            },
            {
                "prospect_id": "p2",
                "profile_url": "https://www.linkedin.com/in/p2/",
                "name": "Pending Two",
                "connection_status": "pending",
            },
        ],
    )

    calls: list[str] = []

    async def probe(url: str) -> bool:
        calls.append(url)
        return False

    def rate_limit_check() -> str | None:
        return "Daily profile view limit reached. Resume tomorrow."

    result = css.run_sync_sweep_sync(
        _default_rcfg(), probe=probe, rate_limit_check=rate_limit_check
    )
    assert calls == []
    assert result.skipped_rate_limited >= 1
    assert "limit" in (result.rate_limit_message or "").lower()
    # No backoff was advanced on the skipped rows.
    rows = json.loads((outreach_tmp / "connections.json").read_text())["connections"]
    assert "sync_backoff" not in rows[0]
    assert "sync_backoff" not in rows[1]


def test_sync_sweep_skips_non_pending_rows(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "connection_status": "connected",
            },
            {
                "prospect_id": "p2",
                "profile_url": "https://www.linkedin.com/in/p2/",
                "connection_status": "ended",
            },
        ],
    )

    calls: list[str] = []

    async def probe(url: str) -> bool:
        calls.append(url)
        return True

    result = css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    assert calls == []
    assert result.checked == 0
    assert result.still_pending == 0


def test_sync_sweep_writes_run_log_entry(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "p1",
                "profile_url": "https://www.linkedin.com/in/p1/",
                "connection_status": "pending",
            }
        ],
    )

    async def probe(_url: str) -> bool:
        return True

    css.run_sync_sweep_sync(_default_rcfg(), probe=probe)
    log_lines = (
        (outreach_tmp / "logs" / "routine_runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert log_lines
    row = json.loads(log_lines[-1])
    assert row["routine_id"] == "connection_sync"
    assert row["kind"] == "sync_sweep"
    assert row["checked"] == 1
    assert row["promoted"] == ["p1"]
