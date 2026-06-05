"""
Per-prospect backoff state for the dashboard's per-prospect routine scheduler.

Each connection row in ``connections.json`` can carry two independent backoff
records:

- ``sync_backoff``: when to next probe ``is_first_degree_connection`` for a row
  whose ``connection_status`` is still ``pending``.
- ``plan_backoff``: when to next dispatch a per-prospect ``conversation-planner``
  Claude call for an actionable row.

Both records share the same shape and the same multiplicative-with-cap policy
(see ``docs/designs/per-connection-routines-with-backoff-design.md``):

- A ``success`` (acceptance detected / message sent / sequence ended) deletes
  the record so the next iteration starts from the routine's configured
  initial interval.
- A ``no_change`` (still pending / no reply yet) multiplies the current
  interval by ``multiplier``, capped at ``max_minutes``.
- A ``tool_error`` applies the same multiplier with ±20% jitter, also capped.

The functions here are pure (no I/O) so they're trivial to unit test.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

BackoffCurveName = Literal["sync", "plan"]
BackoffResult = Literal["success", "no_change", "tool_error"]


# Field names used inside backoff dict on a connection row.
KEY_INTERVAL = "current_interval_minutes"
KEY_LAST_AT = "last_check_at"
KEY_NEXT_AT = "next_check_at"
KEY_LAST_RESULT = "last_result"
KEY_LAST_ERROR = "last_error"
KEY_CONSECUTIVE = "consecutive_no_change"


@dataclass(frozen=True)
class BackoffPolicy:
    """Configuration values that drive ``apply_result`` for one curve."""

    initial_minutes: int
    multiplier: float
    max_minutes: int
    error_jitter: bool = True

    @staticmethod
    def from_config(raw: dict[str, Any] | None, *, defaults: "BackoffPolicy") -> "BackoffPolicy":
        """Build a policy from a possibly-partial config dict, falling back to defaults."""
        cfg = raw if isinstance(raw, dict) else {}
        try:
            initial = int(cfg.get("initial_minutes", defaults.initial_minutes))
        except (TypeError, ValueError):
            initial = defaults.initial_minutes
        try:
            multiplier = float(cfg.get("multiplier", defaults.multiplier))
        except (TypeError, ValueError):
            multiplier = defaults.multiplier
        try:
            max_min = int(cfg.get("max_minutes", defaults.max_minutes))
        except (TypeError, ValueError):
            max_min = defaults.max_minutes
        jitter_raw = cfg.get("error_jitter", defaults.error_jitter)
        if isinstance(jitter_raw, str):
            jitter = jitter_raw.strip().lower() in ("1", "true", "yes")
        else:
            jitter = bool(jitter_raw)

        return BackoffPolicy(
            initial_minutes=max(1, initial),
            multiplier=max(1.0, multiplier),
            max_minutes=max(1, max_min),
            error_jitter=jitter,
        )


# Conservative defaults that match the design doc table.
SYNC_DEFAULT = BackoffPolicy(
    initial_minutes=30,
    multiplier=3.0,
    max_minutes=1000000,
    error_jitter=True,
)

PLAN_DEFAULT = BackoffPolicy(
    initial_minutes=10,
    multiplier=3.0,
    max_minutes=1000000,
    error_jitter=True,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _next_interval(
    prev_minutes: int,
    policy: BackoffPolicy,
    *,
    with_jitter: bool,
    rng: random.Random | None = None,
) -> int:
    """Multiplicative bump with cap; optional jitter ±20% on errors."""
    base = max(1, int(round(prev_minutes * policy.multiplier)))
    if with_jitter:
        r = rng or random
        base = int(round(base * r.uniform(0.8, 1.2)))
    return max(1, min(base, policy.max_minutes))


def is_due(
    backoff: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True when ``next_check_at`` is missing or already past.

    A row with no backoff record is always due — that's how new prospects get
    picked up on the first sweep.
    """
    if not isinstance(backoff, dict):
        return True
    nxt = _parse_iso(backoff.get(KEY_NEXT_AT))
    if nxt is None:
        return True
    return (now or _utcnow()) >= nxt


def apply_result(
    previous: dict[str, Any] | None,
    *,
    policy: BackoffPolicy,
    result: BackoffResult,
    now: datetime | None = None,
    error: str | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Return the next backoff record after observing ``result``.

    Returning ``None`` means the caller should *delete* the backoff field on
    the row (we hit the reset condition for this curve).
    """
    if result == "success":
        # Acceptance / message sent / sequence ended — caller drops the record.
        return None

    now = now or _utcnow()
    prev_interval = policy.initial_minutes
    prev_consecutive = 0
    if isinstance(previous, dict):
        try:
            prev_interval = int(previous.get(KEY_INTERVAL, policy.initial_minutes))
        except (TypeError, ValueError):
            prev_interval = policy.initial_minutes
        try:
            prev_consecutive = int(previous.get(KEY_CONSECUTIVE, 0))
        except (TypeError, ValueError):
            prev_consecutive = 0

    if previous is None:
        # First time bumping — start from the configured initial interval, not
        # from the cap, so an unlucky first probe doesn't push the next check
        # all the way out.
        prev_interval = policy.initial_minutes

    with_jitter = result == "tool_error" and policy.error_jitter
    next_min = _next_interval(prev_interval, policy, with_jitter=with_jitter, rng=rng)

    next_at = now + timedelta(minutes=next_min)
    record: dict[str, Any] = {
        KEY_INTERVAL: next_min,
        KEY_LAST_AT: now.isoformat(),
        KEY_NEXT_AT: next_at.isoformat(),
        KEY_LAST_RESULT: result,
        KEY_LAST_ERROR: error if result == "tool_error" else None,
        KEY_CONSECUTIVE: prev_consecutive + 1 if result == "no_change" else prev_consecutive,
    }
    return record


def reschedule_to_window(
    backoff: dict[str, Any] | None,
    *,
    window_start: str | None,
    window_end: str | None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Push ``next_check_at`` to the next active-window opening if it landed outside.

    Server-local timezone, matching ``web.routines_config.in_active_window``.
    """
    if not isinstance(backoff, dict) or not window_start or not window_end:
        return backoff
    if window_start == window_end:
        return backoff

    nxt = _parse_iso(backoff.get(KEY_NEXT_AT))
    if nxt is None:
        return backoff

    # Convert next_at to server-local time for window comparison.
    local_next = nxt.astimezone()
    start_h, start_m = (int(x) for x in window_start.split(":"))
    end_h, end_m = (int(x) for x in window_end.split(":"))
    start_min = start_h * 60 + start_m
    end_min = end_h * 60 + end_m
    next_min = local_next.hour * 60 + local_next.minute

    if start_min < end_min:
        # Same-day window.
        if start_min <= next_min < end_min:
            return backoff
        if next_min < start_min:
            adjusted = local_next.replace(
                hour=start_h, minute=start_m, second=0, microsecond=0
            )
        else:
            adjusted = local_next.replace(
                hour=start_h, minute=start_m, second=0, microsecond=0
            ) + timedelta(days=1)
    else:
        # Window crosses midnight, e.g. 22:00–06:00.
        if next_min >= start_min or next_min < end_min:
            return backoff
        adjusted = local_next.replace(
            hour=start_h, minute=start_m, second=0, microsecond=0
        )

    updated = dict(backoff)
    updated[KEY_NEXT_AT] = adjusted.astimezone(timezone.utc).isoformat()
    return updated


__all__ = [
    "BackoffPolicy",
    "BackoffResult",
    "PLAN_DEFAULT",
    "SYNC_DEFAULT",
    "apply_result",
    "is_due",
    "reschedule_to_window",
]
