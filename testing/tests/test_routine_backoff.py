"""Unit tests for the per-prospect backoff math."""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from cron.routine_backoff import (  # noqa: E402
    KEY_INTERVAL,
    KEY_LAST_AT,
    KEY_LAST_ERROR,
    KEY_LAST_RESULT,
    KEY_NEXT_AT,
    PLAN_DEFAULT,
    SYNC_DEFAULT,
    BackoffPolicy,
    apply_result,
    is_due,
    reschedule_to_window,
)


NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_default_policies_match_design_doc() -> None:
    assert SYNC_DEFAULT.initial_minutes == 30
    assert SYNC_DEFAULT.multiplier == pytest.approx(1.5)
    assert SYNC_DEFAULT.max_minutes == 24 * 60
    assert PLAN_DEFAULT.initial_minutes == 60
    assert PLAN_DEFAULT.multiplier == pytest.approx(2.0)
    assert PLAN_DEFAULT.max_minutes == 12 * 60


def test_from_config_uses_defaults_on_missing_keys() -> None:
    policy = BackoffPolicy.from_config(None, defaults=SYNC_DEFAULT)
    assert policy == SYNC_DEFAULT
    policy = BackoffPolicy.from_config({"multiplier": 3.0}, defaults=SYNC_DEFAULT)
    assert policy.multiplier == pytest.approx(3.0)
    assert policy.initial_minutes == SYNC_DEFAULT.initial_minutes


def test_from_config_coerces_strings_and_clamps_below_one() -> None:
    policy = BackoffPolicy.from_config(
        {"initial_minutes": "0", "multiplier": "0.5", "max_minutes": "0"},
        defaults=SYNC_DEFAULT,
    )
    assert policy.initial_minutes == 1
    assert policy.multiplier == 1.0
    assert policy.max_minutes == 1


def test_is_due_when_no_record_or_past_next() -> None:
    assert is_due(None, now=NOW) is True
    assert is_due({}, now=NOW) is True
    past = (NOW - timedelta(minutes=1)).isoformat()
    assert is_due({KEY_NEXT_AT: past}, now=NOW) is True
    future = (NOW + timedelta(minutes=1)).isoformat()
    assert is_due({KEY_NEXT_AT: future}, now=NOW) is False


def test_apply_no_change_starts_from_initial() -> None:
    record = apply_result(None, policy=SYNC_DEFAULT, result="no_change", now=NOW)
    assert record is not None
    # First bump: 30 * 1.5 = 45 minutes.
    assert record[KEY_INTERVAL] == 45
    expected_next = NOW + timedelta(minutes=45)
    assert record[KEY_NEXT_AT] == expected_next.isoformat()
    assert record[KEY_LAST_RESULT] == "no_change"
    assert record[KEY_LAST_ERROR] is None


def test_apply_no_change_multiplies_existing_interval() -> None:
    prev = {KEY_INTERVAL: 45, KEY_NEXT_AT: NOW.isoformat()}
    record = apply_result(prev, policy=SYNC_DEFAULT, result="no_change", now=NOW)
    assert record is not None
    # 45 * 1.5 = 67.5 → 68 (rounded).
    assert record[KEY_INTERVAL] == 68


def test_apply_caps_at_max() -> None:
    huge = {KEY_INTERVAL: 5000}
    record = apply_result(huge, policy=SYNC_DEFAULT, result="no_change", now=NOW)
    assert record is not None
    assert record[KEY_INTERVAL] == SYNC_DEFAULT.max_minutes


def test_apply_success_deletes_record() -> None:
    record = apply_result(
        {KEY_INTERVAL: 100}, policy=SYNC_DEFAULT, result="success", now=NOW
    )
    assert record is None


def test_apply_tool_error_uses_jitter_when_enabled() -> None:
    rng = random.Random(42)
    record = apply_result(
        {KEY_INTERVAL: 60},
        policy=SYNC_DEFAULT,
        result="tool_error",
        now=NOW,
        error="boom",
        rng=rng,
    )
    assert record is not None
    # Without jitter would be 90; with ±20% jitter expect 72..108.
    assert 72 <= record[KEY_INTERVAL] <= 108
    assert record[KEY_LAST_RESULT] == "tool_error"
    assert record[KEY_LAST_ERROR] == "boom"


def test_apply_tool_error_no_jitter_policy() -> None:
    policy = BackoffPolicy(
        initial_minutes=10, multiplier=2.0, max_minutes=1000, error_jitter=False
    )
    record = apply_result(
        {KEY_INTERVAL: 20},
        policy=policy,
        result="tool_error",
        now=NOW,
        error="boom",
    )
    assert record is not None
    assert record[KEY_INTERVAL] == 40


def test_reschedule_to_window_no_op_without_window() -> None:
    record = {KEY_NEXT_AT: NOW.isoformat()}
    assert reschedule_to_window(record, window_start=None, window_end=None) == record


def test_reschedule_to_window_same_day_pushes_forward() -> None:
    # Server-local 03:00 falls outside 09:00–17:00; should push to next 09:00.
    local_three_am = datetime(2026, 5, 28, 3, 0, 0).astimezone()
    record = {KEY_NEXT_AT: local_three_am.astimezone(timezone.utc).isoformat()}
    updated = reschedule_to_window(record, window_start="09:00", window_end="17:00")
    assert updated is not None
    # The window-open time same date, in local TZ.
    expected_local = local_three_am.replace(hour=9, minute=0, second=0, microsecond=0)
    expected = expected_local.astimezone(timezone.utc).isoformat()
    assert updated[KEY_NEXT_AT] == expected


def test_reschedule_to_window_inside_window_unchanged() -> None:
    local_noon = datetime(2026, 5, 28, 12, 0, 0).astimezone()
    record = {KEY_NEXT_AT: local_noon.astimezone(timezone.utc).isoformat()}
    updated = reschedule_to_window(record, window_start="09:00", window_end="17:00")
    assert updated == record


def test_reschedule_to_window_after_window_pushes_to_next_day() -> None:
    local_evening = datetime(2026, 5, 28, 20, 0, 0).astimezone()
    record = {KEY_NEXT_AT: local_evening.astimezone(timezone.utc).isoformat()}
    updated = reschedule_to_window(record, window_start="09:00", window_end="17:00")
    assert updated is not None
    expected_local = local_evening.replace(
        hour=9, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)
    expected = expected_local.astimezone(timezone.utc).isoformat()
    assert updated[KEY_NEXT_AT] == expected


def test_reschedule_to_window_handles_overnight_window() -> None:
    # 22:00–06:00 window. 03:00 local is inside.
    local_three = datetime(2026, 5, 28, 3, 0, 0).astimezone()
    record = {KEY_NEXT_AT: local_three.astimezone(timezone.utc).isoformat()}
    updated = reschedule_to_window(record, window_start="22:00", window_end="06:00")
    assert updated == record


def test_consecutive_counter_increments_on_no_change() -> None:
    record = apply_result(None, policy=SYNC_DEFAULT, result="no_change", now=NOW)
    assert record is not None and record["consecutive_no_change"] == 1
    record2 = apply_result(record, policy=SYNC_DEFAULT, result="no_change", now=NOW)
    assert record2 is not None and record2["consecutive_no_change"] == 2
