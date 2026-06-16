"""Tests for tools/rate_limits.py."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Core tools/ (rate_limits.py stays in the production core)
_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import rate_limits as rl  # noqa: E402


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EBASE_HOME", str(tmp_path))
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS", raising=False)
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_DMS", raising=False)
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_PROFILE_VIEWS", raising=False)
    # Clear alias env vars too
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_CONNECTIONS", raising=False)
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_MESSAGES", raising=False)
    monkeypatch.delenv("LINKEDIN_RATE_LIMIT_VIEWS", raising=False)
    yield tmp_path


def test_rate_limit_blocks_at_cap(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS", "2")

    assert rl.rate_limit("connection_request", record=True) is None
    assert rl.rate_limit("connection_request", record=True) is None
    err = rl.rate_limit("connection_request", record=False)
    assert err == rl._ERROR_MESSAGES[rl.REQUEST_CONNECTION]


def test_rate_limit_check_does_not_consume(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_DMS", "1")

    assert rl.rate_limit("dm", record=False) is None
    assert rl.rate_limit("dm", record=False) is None
    assert rl.rate_limit("dm", record=True) is None
    assert rl.rate_limit("dm", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_DM]


def test_day_rollover_clears_queue(isolated_home: Path):
    path = rl.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    path.write_text(
        json.dumps(
            {
                "day": yesterday,
                "connection_requests": [{"at": "2020-01-01T00:00:00"}],
                "dms": [],
                "profile_views": [],
            }
        ),
        encoding="utf-8",
    )

    assert rl.rate_limit("connection_request", record=False) is None
    snap = rl.get_usage_snapshot()
    assert snap["day"] == rl._local_day_key()
    assert snap["usage"]["connection_request"] == 0


def test_config_json_limits(isolated_home: Path):
    cfg = isolated_home / "config.json"
    cfg.write_text(
        json.dumps({"rate_limits": {"profile_views_per_day": 1}}),
        encoding="utf-8",
    )

    assert rl.rate_limit("profile_view", record=True) is None
    assert (
        rl.rate_limit("profile_view", record=False)
        == rl._ERROR_MESSAGES[rl.REQUEST_PROFILE_VIEW]
    )


def test_alias_env_vars(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    """Alias env vars from the issue spec (CONNECTIONS/MESSAGES/VIEWS) are respected."""
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTIONS", "1")
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_MESSAGES", "1")
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_VIEWS", "1")

    assert rl.rate_limit("connection_request", record=True) is None
    assert rl.rate_limit("connection_request", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_CONNECTION]

    assert rl.rate_limit("dm", record=True) is None
    assert rl.rate_limit("dm", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_DM]

    assert rl.rate_limit("profile_view", record=True) is None
    assert rl.rate_limit("profile_view", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_PROFILE_VIEW]


def test_malformed_primary_falls_through_to_alias(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    """Malformed primary env var falls through to valid alias."""
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS", "not-a-number")
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTIONS", "1")

    assert rl.rate_limit("connection_request", record=True) is None
    assert rl.rate_limit("connection_request", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_CONNECTION]


def test_primary_env_overrides_alias(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    """Primary env var takes precedence over alias when both are set."""
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS", "2")
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTIONS", "1")  # alias — should be ignored

    assert rl.rate_limit("connection_request", record=True) is None
    assert rl.rate_limit("connection_request", record=True) is None
    assert rl.rate_limit("connection_request", record=False) == rl._ERROR_MESSAGES[rl.REQUEST_CONNECTION]


def test_disabled_skips_limits(isolated_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS", "0")
    monkeypatch.setenv("LINKEDIN_RATE_LIMIT_DISABLED", "1")

    for _ in range(5):
        assert rl.rate_limit("connection_request", record=True) is None
