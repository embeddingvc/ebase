"""
Daily rate limits for LinkedIn MCP tools (connection requests, DMs, profile views).

State: ``~/.linkedin-outreach/rate_limits.json`` (override with ``LINKEDIN_OUTREACH_HOME``).
Limits: env vars, then ``~/.linkedin-outreach/config.json`` → ``rate_limits``, then defaults.

Day boundaries use the local timezone (``datetime.now().astimezone().tzinfo``).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("linkedin.rate_limits")

# ── Request names (public API) ────────────────────────────────────────────────

REQUEST_CONNECTION = "connection_request"
REQUEST_DM = "dm"
REQUEST_PROFILE_VIEW = "profile_view"

_VALID_REQUESTS = frozenset({
    REQUEST_CONNECTION,
    REQUEST_DM,
    REQUEST_PROFILE_VIEW,
})

# Internal queue keys in rate_limits.json
_CATEGORY_CONNECTION = "connection_requests"
_CATEGORY_DM = "dms"
_CATEGORY_PROFILE_VIEW = "profile_views"

_REQUEST_TO_CATEGORY = {
    REQUEST_CONNECTION: _CATEGORY_CONNECTION,
    REQUEST_DM: _CATEGORY_DM,
    REQUEST_PROFILE_VIEW: _CATEGORY_PROFILE_VIEW,
}

_LIMIT_ENV = {
    _CATEGORY_CONNECTION: "LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS",
    _CATEGORY_DM: "LINKEDIN_RATE_LIMIT_DMS",
    _CATEGORY_PROFILE_VIEW: "LINKEDIN_RATE_LIMIT_PROFILE_VIEWS",
}

_CONFIG_KEYS = {
    _CATEGORY_CONNECTION: "connection_requests_per_day",
    _CATEGORY_DM: "dms_per_day",
    _CATEGORY_PROFILE_VIEW: "profile_views_per_day",
}

_DEFAULT_LIMITS = {
    _CATEGORY_CONNECTION: 25,
    _CATEGORY_DM: 50,
    _CATEGORY_PROFILE_VIEW: 100,
}

_ERROR_MESSAGES = {
    REQUEST_CONNECTION: (
        "Daily connection request limit reached. Resume tomorrow."
    ),
    REQUEST_DM: "Daily DM limit reached. Resume tomorrow.",
    REQUEST_PROFILE_VIEW: (
        "Daily profile view limit reached. Resume tomorrow."
    ),
}

# ── Paths ─────────────────────────────────────────────────────────────────────


def outreach_home() -> Path:
    raw = os.environ.get("LINKEDIN_OUTREACH_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".linkedin-outreach"


def config_path() -> Path:
    return outreach_home() / "config.json"


def state_path() -> Path:
    return outreach_home() / "rate_limits.json"


# ── Config / limits ───────────────────────────────────────────────────────────


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("could not read %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def rate_limits_disabled() -> bool:
    flag = os.environ.get("LINKEDIN_RATE_LIMIT_DISABLED", "").strip().lower()
    return flag in ("1", "true", "yes")


def get_limits() -> dict[str, int]:
    """Resolved daily caps keyed by internal category name."""
    cfg = _read_json_file(config_path()).get("rate_limits") or {}
    if not isinstance(cfg, dict):
        cfg = {}

    limits: dict[str, int] = {}
    for category, default in _DEFAULT_LIMITS.items():
        env_key = _LIMIT_ENV[category]
        env_val = os.environ.get(env_key, "").strip()
        if env_val:
            try:
                limits[category] = max(0, int(env_val))
                continue
            except ValueError:
                logger.warning("invalid %s=%r; using config/default", env_key, env_val)

        cfg_key = _CONFIG_KEYS[category]
        cfg_val = cfg.get(cfg_key)
        if cfg_val is not None:
            try:
                limits[category] = max(0, int(cfg_val))
                continue
            except (TypeError, ValueError):
                logger.warning(
                    "invalid config rate_limits.%s=%r; using default",
                    cfg_key,
                    cfg_val,
                )

        limits[category] = default
    return limits


# ── Day rollover ──────────────────────────────────────────────────────────────


def _local_today() -> date:
    return datetime.now().astimezone().date()


def _local_day_key(d: date | None = None) -> str:
    return (d or _local_today()).isoformat()


def _empty_state_for_today() -> dict[str, Any]:
    return {
        "day": _local_day_key(),
        _CATEGORY_CONNECTION: [],
        _CATEGORY_DM: [],
        _CATEGORY_PROFILE_VIEW: [],
    }


def _rollover_state(state: dict[str, Any]) -> dict[str, Any]:
    """Reset queues when the stored day is before today (local midnight)."""
    today = _local_day_key()
    if state.get("day") == today:
        for key in (
            _CATEGORY_CONNECTION,
            _CATEGORY_DM,
            _CATEGORY_PROFILE_VIEW,
        ):
            if not isinstance(state.get(key), list):
                state[key] = []
        return state
    logger.info(
        "rate limit day rollover  previous_day=%s  today=%s",
        state.get("day"),
        today,
    )
    return _empty_state_for_today()


# ── Persistence (locked read/modify/write) ────────────────────────────────────


def _with_locked_state(
    mutator: Any,
) -> Any:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            raw = fh.read()
            if raw.strip():
                try:
                    state = json.loads(raw)
                except json.JSONDecodeError:
                    state = {}
            else:
                state = {}
            if not isinstance(state, dict):
                state = {}

            state = _rollover_state(state)
            result = mutator(state)

            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            return result
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ── Single public entry point ─────────────────────────────────────────────────


def rate_limit(
    request_name: str,
    *,
    profile_url: str = "",
    record: bool = False,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """
    Enforce a daily cap for one request type.

    Each call loads ``rate_limits.json``, clears stale day queues (local midnight
    rollover), counts today's events for ``request_name``, and returns an error
    string when the cap is reached.

    Parameters
    ----------
    request_name : str
        One of ``connection_request``, ``dm``, ``profile_view``.
    profile_url : str
        Optional URL stored on the queued event.
    record : bool
        If False, check only. If True, append one event after the check passes
        (call after a successful LinkedIn action).
    extra : dict | None
        Optional fields merged into the recorded event.

    Returns
    -------
    str | None
        Error message when limited; None when allowed (and recorded if requested).
    """
    if rate_limits_disabled():
        return None

    name = (request_name or "").strip()
    if name not in _VALID_REQUESTS:
        logger.warning("unknown rate_limit request_name=%r", request_name)
        return None

    category = _REQUEST_TO_CATEGORY[name]
    limits = get_limits()
    cap = limits.get(category, _DEFAULT_LIMITS[category])

    event: dict[str, Any] = {
        "at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    if profile_url:
        event["profile_url"] = profile_url.strip()
    if extra:
        event.update(extra)

    def _mut(state: dict[str, Any]) -> str | None:
        entries = state.get(category, [])
        count = len(entries) if isinstance(entries, list) else 0

        if count >= cap:
            msg = _ERROR_MESSAGES[name]
            logger.warning(
                "rate limit hit  request=%s  count=%d  cap=%d  url=%s",
                name,
                count,
                cap,
                profile_url,
            )
            return msg

        if record:
            if not isinstance(entries, list):
                entries = []
            entries.append(event)
            state[category] = entries

        return None

    return _with_locked_state(_mut)


def get_usage_snapshot() -> dict[str, Any]:
    """Current counts and limits (for tests / debugging)."""
    limits = get_limits()

    def _read(state: dict[str, Any]) -> dict[str, Any]:
        usage = {}
        for req, cat in _REQUEST_TO_CATEGORY.items():
            entries = state.get(cat, [])
            usage[req] = len(entries) if isinstance(entries, list) else 0
        return {
            "day": state.get("day"),
            "limits": {
                req: limits.get(_REQUEST_TO_CATEGORY[req], _DEFAULT_LIMITS[_REQUEST_TO_CATEGORY[req]])
                for req in _VALID_REQUESTS
            },
            "usage": usage,
            "disabled": rate_limits_disabled(),
            "state_path": str(state_path()),
        }

    path = state_path()
    if not path.is_file():
        return _read(_empty_state_for_today())
    return _with_locked_state(lambda s: _read(dict(s)))
