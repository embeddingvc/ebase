"""Tests for dashboard routine configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from web import routines_config as rc  # noqa: E402


def test_validate_routine_rejects_bad_skill() -> None:
    err = rc.validate_routine(
        {"name": "X", "skill": "not-a-real-skill", "interval_minutes": 10, "active": True}
    )
    assert err is not None


def test_migrate_legacy_stage_routines() -> None:
    legacy = [
        {
            "id": "initial_connect",
            "name": "Initial Connect",
            "icon": "auto_fix_high",
            "stages": "cold,pending_connection",
            "prospect_count": 2,
            "status": "active",
        }
    ]
    migrated = rc._migrate_routines(legacy)
    assert len(migrated) == 2
    assert migrated[0]["skill"] == "sync-pending-connections"
    assert migrated[0]["interval_minutes"] == 30
    assert migrated[0]["active"] is False


def test_get_routines_display_includes_skill_fields() -> None:
    row = rc.to_display_routine(
        {
            "id": "t1",
            "name": "Sync",
            "skill": "sync-pending-connections",
            "interval_minutes": 30,
            "active": False,
        }
    )
    assert row["skill"] == "sync-pending-connections"
    assert row["interval_minutes"] == 30
    assert row["status"] == "disabled"


def test_upsert_routines_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "outreach"
    (base / "config").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")

    data = rc.upsert_routines(
        [
            {
                "id": "t1",
                "name": "Sync",
                "skill": "sync-pending-connections",
                "interval_minutes": 15,
                "active": True,
            }
        ]
    )
    assert data["total"] == 1
    assert data["routines"][0]["skill"] == "sync-pending-connections"
