"""Tests for outreach.stats (get_outreach_stats aggregation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from outreach import stats as st


def _conv(prospect_id: str, **overrides) -> dict:
    row = {
        "prospect_id": prospect_id,
        "outreach_stage": "engaged",
        "end_goal": "schedule_meeting",
        "last_action_timestamp": "2026-06-25T05:52:00+00:00",
        "messages": [],
        "ended_reason": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def outreach_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "outreach"
    (base / "conversations").mkdir(parents=True)
    (base / "prospects").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    return base


def _write(base: Path, sub: str, name: str, data: dict) -> None:
    (base / sub / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_empty_data_root(outreach_tmp: Path) -> None:
    result = st.build_outreach_stats()
    assert result["pipeline"] == {"total": 0, "by_stage": {}}
    assert result["connections"]["sent"] == 0
    assert result["connections"]["acceptance_rate_pct"] == 0.0
    assert result["replies"]["reply_rate_pct"] == 0.0
    assert result["sequence"]["by_step"] == {}
    assert result["by_end_goal"] == {}


def test_funnel_and_reply_rates(outreach_tmp: Path) -> None:
    (outreach_tmp / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {"prospect_id": "a", "connection_status": "connected", "connected_at": "2026-06-01T00:00:00+00:00"},
                    {"prospect_id": "b", "connection_status": "ended", "connected_at": "2026-06-01T00:00:00+00:00"},
                    {"prospect_id": "c", "connection_status": "pending", "connected_at": "2026-06-01T00:00:00+00:00"},
                ]
            }
        ),
        encoding="utf-8",
    )

    # a: replied at step 1, converted via resume_received.
    _write(
        outreach_tmp,
        "conversations",
        "a",
        _conv(
            "a",
            outreach_stage="converted",
            ended_reason="resume_received",
            messages=[
                {"sender": "operator", "text": "hi", "timestamp": "t1", "sequence_step": 1},
                {"sender": "prospect", "text": "hey", "timestamp": "t2"},
            ],
        ),
    )
    # b: no reply, ended with no_response.
    _write(
        outreach_tmp,
        "conversations",
        "b",
        _conv(
            "b",
            outreach_stage="ended",
            ended_reason="no_response",
            messages=[{"sender": "operator", "text": "hi", "timestamp": "t1", "sequence_step": 1}],
        ),
    )
    # c: still pending, no conversation activity yet -> cold.
    _write(outreach_tmp, "conversations", "c", _conv("c", outreach_stage="cold", end_goal="obtain_resume", messages=[]))

    result = st.build_outreach_stats()

    assert result["pipeline"]["total"] == 3
    assert result["pipeline"]["by_stage"] == {"converted": 1, "ended": 1, "cold": 1}

    assert result["connections"] == {
        "sent": 3,
        "accepted": 2,
        "pending": 1,
        "ended": 1,
        "acceptance_rate_pct": 66.7,
    }

    assert result["replies"]["total_replied"] == 1
    assert result["replies"]["reply_rate_pct"] == 50.0

    assert result["outcomes"]["total_converted"] == 1
    assert result["outcomes"]["conversion_rate_pct"] == 50.0
    assert result["outcomes"]["by_ended_reason"] == {"resume_received": 1, "no_response": 1}

    assert result["sequence"]["by_step"]["1"] == {"sent": 2, "got_reply": 1, "reply_rate_pct": 50.0}

    assert result["by_end_goal"]["schedule_meeting"] == {"total": 2, "converted": 1, "rate_pct": 50.0}
    assert result["by_end_goal"]["obtain_resume"] == {"total": 1, "converted": 0, "rate_pct": 0.0}


def test_since_filters_out_old_activity(outreach_tmp: Path) -> None:
    (outreach_tmp / "connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {"prospect_id": "old", "connection_status": "connected", "connected_at": "2026-01-01T00:00:00+00:00"},
                    {"prospect_id": "new", "connection_status": "connected", "connected_at": "2026-06-30T00:00:00+00:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write(outreach_tmp, "conversations", "old", _conv("old", last_action_timestamp="2026-01-01T00:00:00+00:00"))
    _write(outreach_tmp, "conversations", "new", _conv("new", last_action_timestamp="2026-06-30T00:00:00+00:00"))

    result = st.build_outreach_stats(since="2026-06-01")

    assert result["pipeline"]["total"] == 1
    assert result["connections"]["sent"] == 1
