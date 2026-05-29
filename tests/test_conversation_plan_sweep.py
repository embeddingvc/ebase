"""Tests for the per-prospect conversation plan sweep."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web import conversation_plan_sweep as cps  # noqa: E402
from web.routine_backoff import PLAN_DEFAULT  # noqa: E402


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "logs").mkdir(parents=True)
    (base / "conversations").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")
    return base


@pytest.fixture(autouse=True)
def _reset_locks() -> None:
    cps._PROSPECT_LOCKS.clear()
    yield
    cps._PROSPECT_LOCKS.clear()


def _write_connections(base: Path, rows: list[dict[str, Any]]) -> None:
    (base / "connections.json").write_text(
        json.dumps({"connections": rows}), encoding="utf-8"
    )


def _write_conversation(base: Path, prospect_id: str, data: dict[str, Any]) -> None:
    (base / "conversations" / f"{prospect_id}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _default_rcfg(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "active": True,
        "active_window_start": None,
        "active_window_end": None,
        "backoff": {
            "initial_minutes": PLAN_DEFAULT.initial_minutes,
            "multiplier": PLAN_DEFAULT.multiplier,
            "max_minutes": PLAN_DEFAULT.max_minutes,
            "error_jitter": False,  # deterministic for tests
        },
    }
    cfg.update(overrides)
    return cfg


def _make_run_result(
    ok: bool = True,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    error: str | None = None,
) -> cps.PlanRunResult:
    return cps.PlanRunResult(
        ok=ok,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        error=error,
    )


def test_plan_sweep_dispatches_one_prospect_per_call(
    outreach_tmp: Path,
) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "alex",
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            },
            {
                "prospect_id": "bea",
                "profile_url": "https://www.linkedin.com/in/bea/",
                "connection_status": "connected",
            },
            {
                "prospect_id": "skip-pending",
                "profile_url": "https://www.linkedin.com/in/skip/",
                "connection_status": "pending",
            },
            {
                "prospect_id": "skip-ended",
                "profile_url": "https://www.linkedin.com/in/skip2/",
                "connection_status": "ended",
            },
        ],
    )

    calls: list[str] = []

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        calls.append(prospect_id)
        # No conversation file → classified as no_action.
        return _make_run_result()

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert sorted(calls) == ["alex", "bea"]
    assert result.actionable == 2
    assert result.dispatched == 2


def test_plan_sweep_treats_recent_last_action_as_sent(outreach_tmp: Path) -> None:
    pid = "alex"
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": pid,
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            }
        ],
    )
    _write_conversation(
        outreach_tmp,
        pid,
        {
            "prospect_id": pid,
            "outreach_stage": "engaged",
            "messages": [],
            "last_action_timestamp": "2020-01-01T00:00:00+00:00",
        },
    )

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        # Simulate the skill upserting a fresh last_action_timestamp.
        conv_path = outreach_tmp / "conversations" / f"{prospect_id}.json"
        data = json.loads(conv_path.read_text())
        data["last_action_timestamp"] = datetime.now(timezone.utc).isoformat()
        conv_path.write_text(json.dumps(data))
        return _make_run_result(stdout="ok — sent")

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert [s["prospect_id"] for s in result.sent] == [pid]
    row = json.loads((outreach_tmp / "connections.json").read_text())["connections"][0]
    # Success outcome resets backoff state.
    assert "plan_backoff" not in row


def test_plan_sweep_treats_terminal_stage_as_ended(outreach_tmp: Path) -> None:
    pid = "alex"
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": pid,
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            }
        ],
    )

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        _write_conversation(
            outreach_tmp,
            prospect_id,
            {
                "prospect_id": prospect_id,
                "outreach_stage": "ended",
                "messages": [],
                "ended_reason": "no_response",
            },
        )
        return _make_run_result(stdout="sequence ended")

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert [e["prospect_id"] for e in result.ended] == [pid]


def test_plan_sweep_no_action_bumps_backoff(outreach_tmp: Path) -> None:
    pid = "alex"
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": pid,
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            }
        ],
    )

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        return _make_run_result(stdout="skipped (no reply yet)")

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert [n["prospect_id"] for n in result.no_action] == [pid]
    row = json.loads((outreach_tmp / "connections.json").read_text())["connections"][0]
    assert "plan_backoff" in row
    # No-action bump: 60 * 2 = 120 minutes.
    assert row["plan_backoff"]["current_interval_minutes"] == 120
    assert row["plan_backoff"]["last_result"] == "no_change"


def test_plan_sweep_tool_error_records_backoff_and_keeps_status(
    outreach_tmp: Path,
) -> None:
    pid = "alex"
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": pid,
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            }
        ],
    )

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        return _make_run_result(
            ok=False,
            returncode=1,
            error="claude exited with status 1",
            stderr="API Error",
        )

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert len(result.errors) == 1
    row = json.loads((outreach_tmp / "connections.json").read_text())["connections"][0]
    # connection_status untouched by an error.
    assert row["connection_status"] == "connected"
    assert row["plan_backoff"]["last_result"] == "tool_error"
    assert "claude" in row["plan_backoff"]["last_error"]


def test_plan_sweep_respects_existing_next_plan(outreach_tmp: Path) -> None:
    pid = "alex"
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": pid,
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
                "plan_backoff": {
                    "current_interval_minutes": 120,
                    "next_check_at": future,
                    "last_result": "no_change",
                },
            }
        ],
    )

    calls: list[str] = []

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        calls.append(prospect_id)
        return _make_run_result()

    result = cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    assert calls == []
    assert result.skipped_not_due == 1


def test_plan_sweep_bails_on_rate_limit(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "alex",
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            },
            {
                "prospect_id": "bea",
                "profile_url": "https://www.linkedin.com/in/bea/",
                "connection_status": "connected",
            },
        ],
    )

    calls: list[str] = []

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        calls.append(prospect_id)
        return _make_run_result()

    def rate_limit_check() -> str | None:
        return "Daily DM limit reached. Resume tomorrow."

    result = cps.run_plan_sweep_sync(
        _default_rcfg(), runner=runner, rate_limit_check=rate_limit_check
    )
    assert calls == []
    assert result.skipped_rate_limited >= 1


def test_plan_sweep_writes_run_log_entry(outreach_tmp: Path) -> None:
    _write_connections(
        outreach_tmp,
        [
            {
                "prospect_id": "alex",
                "profile_url": "https://www.linkedin.com/in/alex/",
                "connection_status": "connected",
            }
        ],
    )

    async def runner(prospect_id: str) -> cps.PlanRunResult:
        return _make_run_result()

    cps.run_plan_sweep_sync(_default_rcfg(), runner=runner)
    log_lines = (
        (outreach_tmp / "logs" / "routine_runs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert log_lines
    row = json.loads(log_lines[-1])
    assert row["routine_id"] == "conversation_plan"
    assert row["kind"] == "plan_sweep"
