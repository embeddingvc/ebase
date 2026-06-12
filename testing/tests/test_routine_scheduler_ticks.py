"""Tests for ``cron.routine_scheduler`` wrapper-level tick logging.

These cover the heartbeat-only branches: when the scheduler considered a
sweep but skipped it because the routine is inactive or the active window
is closed, a tick row should still be written to ``routine_ticks.jsonl``
so the operator can confirm the scheduler is alive.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from cron import routine_scheduler as rs  # noqa: E402


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "logs").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")
    # Reset per-sweep locks between tests so a stale lock from a previous
    # test can't poison the wrapper-skipped path.
    rs._sweep_locks.clear()
    rs._last_sweep_at.clear()
    return base


def _ticks_path(base: Path) -> Path:
    return base / "logs" / "routine_ticks.jsonl"


def _read_ticks(base: Path) -> list[dict[str, Any]]:
    p = _ticks_path(base)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def test_sync_sweep_wrapper_records_tick_when_inactive(outreach_tmp: Path) -> None:
    """A disabled connection_sync row produces an ``inactive`` tick row."""
    rcfg = {"active": False, "active_window_start": None, "active_window_end": None}
    asyncio.run(rs._run_sync_sweep_routine(rcfg))
    rows = _read_ticks(outreach_tmp)
    assert rows, "expected a tick row for inactive routine"
    assert rows[-1]["routine_id"] == "connection_sync"
    assert rows[-1]["status"] == "skipped"
    assert rows[-1]["reason"] == "inactive"


def test_plan_sweep_wrapper_records_tick_when_outside_window(
    outreach_tmp: Path,
) -> None:
    """A 09:00–09:00 window is treated as ``outside_window`` (degenerate)."""
    rcfg = {
        "active": True,
        "active_window_start": "09:00",
        "active_window_end": "09:00",
    }
    asyncio.run(rs._run_plan_sweep_routine(rcfg))
    rows = _read_ticks(outreach_tmp)
    assert rows, "expected a tick row for outside-window routine"
    assert rows[-1]["routine_id"] == "conversation_plan"
    assert rows[-1]["status"] == "skipped"
    assert rows[-1]["reason"] == "outside_window"
