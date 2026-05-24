"""Tests for dashboard routine configuration."""

from __future__ import annotations

import sys
from datetime import datetime
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
    assert migrated[0]["active"] is True


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


def _valid_row(**overrides: object) -> dict[str, object]:
    base = {
        "id": "t1",
        "name": "Sync",
        "skill": "sync-pending-connections",
        "interval_minutes": 15,
        "active": True,
    }
    base.update(overrides)
    return base


def test_validate_routine_accepts_blank_window() -> None:
    assert rc.validate_routine(_valid_row()) is None
    assert (
        rc.validate_routine(
            _valid_row(active_window_start=None, active_window_end=None)
        )
        is None
    )
    assert (
        rc.validate_routine(_valid_row(active_window_start="", active_window_end=""))
        is None
    )


def test_validate_routine_accepts_full_window() -> None:
    assert (
        rc.validate_routine(
            _valid_row(active_window_start="09:00", active_window_end="17:30")
        )
        is None
    )
    assert (
        rc.validate_routine(
            _valid_row(active_window_start="22:00", active_window_end="06:00")
        )
        is None
    )


def test_validate_routine_rejects_partial_window() -> None:
    err = rc.validate_routine(
        _valid_row(active_window_start="09:00", active_window_end=None)
    )
    assert err is not None and "both" in err


def test_validate_routine_rejects_equal_window() -> None:
    err = rc.validate_routine(
        _valid_row(active_window_start="09:00", active_window_end="09:00")
    )
    assert err is not None and "differ" in err


def test_validate_routine_rejects_malformed_window() -> None:
    err = rc.validate_routine(
        _valid_row(active_window_start="9am", active_window_end="5pm")
    )
    assert err is not None and "HH:MM" in err
    err = rc.validate_routine(
        _valid_row(active_window_start="24:00", active_window_end="06:00")
    )
    assert err is not None


def test_in_active_window_no_restriction() -> None:
    row = {"active_window_start": None, "active_window_end": None}
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 3, 14)) is True


def test_in_active_window_same_day() -> None:
    row = {"active_window_start": "09:00", "active_window_end": "17:00"}
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 9, 0)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 12, 30)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 16, 59)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 17, 0)) is False
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 8, 59)) is False


def test_in_active_window_crosses_midnight() -> None:
    row = {"active_window_start": "22:00", "active_window_end": "06:00"}
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 22, 0)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 23, 23, 59)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 24, 0, 0)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 24, 5, 59)) is True
    assert rc.in_active_window(row, now=datetime(2026, 5, 24, 6, 0)) is False
    assert rc.in_active_window(row, now=datetime(2026, 5, 24, 21, 59)) is False


def test_upsert_routines_persists_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
                "active_window_start": "09:00",
                "active_window_end": "17:00",
            }
        ]
    )
    row = data["routines"][0]
    assert row["active_window_start"] == "09:00"
    assert row["active_window_end"] == "17:00"

    display = rc.get_routines_display()["routines"][0]
    assert display["active_window_label"] == "09:00\u201317:00"


def test_upsert_routines_rejects_bad_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "outreach"
    (base / "config").mkdir(parents=True)
    monkeypatch.setenv("OUTREACH_DATA_ROOT", str(base))
    monkeypatch.setenv("OUTREACH_MOCK", "0")

    with pytest.raises(ValueError):
        rc.upsert_routines(
            [
                {
                    "id": "t1",
                    "name": "Sync",
                    "skill": "sync-pending-connections",
                    "interval_minutes": 15,
                    "active": True,
                    "active_window_start": "09:00",
                    "active_window_end": None,
                }
            ]
        )
