"""
Deterministic connection-sync sweep (no LLM).

Walks ``connections.json`` rows whose ``connection_status == "pending"``,
calls ``is_first_degree_connection`` for each row whose ``sync_backoff``
says it is due, promotes accepted invites to ``connected``, and advances
the per-row backoff state on every observation.

This module replaces the ``sync-pending-connections`` Claude skill in the
``per_prospect`` scheduler mode (see
``docs/designs/per-connection-routines-with-backoff-design.md``). The skill
is still installed for ad-hoc operator use in Claude Code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from web.dashboard_data import _atomic_write_json, _read_json, outreach_base
from web.routine_backoff import (
    BackoffPolicy,
    SYNC_DEFAULT,
    apply_result,
    is_due,
    reschedule_to_window,
)

logger = logging.getLogger("web.connection_sync_sweep")

CONNECTIONS_FILE = "connections.json"
ACTIONS_LOG = "logs/actions.jsonl"
RUNS_LOG = "logs/routine_runs.jsonl"

SyncProbe = Callable[[str], Awaitable[bool | str]]
"""Async callable returning either ``True``/``False`` or an error string."""


@dataclass
class SyncSweepResult:
    checked: int = 0
    promoted: list[dict[str, Any]] = field(default_factory=list)
    still_pending: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped_rate_limited: int = 0
    skipped_not_due: int = 0
    rate_limit_message: str | None = None

    def to_log_row(self) -> dict[str, Any]:
        return {
            "kind": "sync_sweep",
            "checked": self.checked,
            "promoted": [p["prospect_id"] for p in self.promoted],
            "still_pending": self.still_pending,
            "errors": self.errors,
            "skipped_rate_limited": self.skipped_rate_limited,
            "skipped_not_due": self.skipped_not_due,
            "rate_limit_message": self.rate_limit_message,
        }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connections_path() -> Path:
    return outreach_base() / CONNECTIONS_FILE


def _load_connections() -> dict[str, Any]:
    data = _read_json(_connections_path(), {"connections": []})
    if not isinstance(data, dict) or not isinstance(data.get("connections"), list):
        return {"connections": []}
    return data


def _save_connections(data: dict[str, Any]) -> None:
    _atomic_write_json(_connections_path(), data)


def _append_jsonl(rel_path: str, row: dict[str, Any]) -> None:
    path = outreach_base() / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _default_live_probe() -> SyncProbe:
    """Live probe that calls the LinkedIn browser directly.

    Imported lazily so unit tests don't need Playwright installed.
    """
    async def _probe(profile_url: str) -> bool | str:
        try:
            # Make tools/ importable so the shared rate_limits module resolves.
            tools_dir = Path(__file__).resolve().parent.parent / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from rate_limits import rate_limit  # type: ignore[import-not-found]
            from outreach.browser import LinkedInBrowser
        except Exception as exc:  # pragma: no cover - import wiring
            return f"error: import failed: {exc}"

        err = rate_limit("profile_view", profile_url=profile_url, record=False)
        if err:
            return f"error: {err}"

        try:
            async with LinkedInBrowser(mode="attach") as li:
                await li.assert_logged_in()
                first = await li.is_first_degree_connection(profile_url)
        except Exception as exc:
            return f"error: browser: {exc}"

        rate_limit("profile_view", profile_url=profile_url, record=True)
        return bool(first)

    return _probe


def _policy_from_config(rcfg: dict[str, Any]) -> BackoffPolicy:
    return BackoffPolicy.from_config(rcfg.get("backoff"), defaults=SYNC_DEFAULT)


def _row_due(row: dict[str, Any], *, now: datetime) -> bool:
    return is_due(row.get("sync_backoff"), now=now)


def _record_no_change(
    row: dict[str, Any],
    *,
    policy: BackoffPolicy,
    rcfg: dict[str, Any],
    now: datetime,
) -> None:
    next_backoff = apply_result(
        row.get("sync_backoff"),
        policy=policy,
        result="no_change",
        now=now,
    )
    next_backoff = reschedule_to_window(
        next_backoff,
        window_start=rcfg.get("active_window_start"),
        window_end=rcfg.get("active_window_end"),
        now=now,
    )
    if next_backoff is None:
        row.pop("sync_backoff", None)
    else:
        row["sync_backoff"] = next_backoff


def _record_error(
    row: dict[str, Any],
    *,
    policy: BackoffPolicy,
    rcfg: dict[str, Any],
    now: datetime,
    error: str,
) -> None:
    next_backoff = apply_result(
        row.get("sync_backoff"),
        policy=policy,
        result="tool_error",
        now=now,
        error=error,
    )
    next_backoff = reschedule_to_window(
        next_backoff,
        window_start=rcfg.get("active_window_start"),
        window_end=rcfg.get("active_window_end"),
        now=now,
    )
    if next_backoff is None:
        row.pop("sync_backoff", None)
    else:
        row["sync_backoff"] = next_backoff


def _record_success(row: dict[str, Any]) -> None:
    # Reset backoff state — the row is now ``connected`` and the sync curve
    # no longer applies.
    row.pop("sync_backoff", None)


async def run_sync_sweep(
    rcfg: dict[str, Any],
    *,
    probe: SyncProbe | None = None,
    rate_limit_check: Callable[[], str | None] | None = None,
    now: datetime | None = None,
) -> SyncSweepResult:
    """Run one pass over all ``pending`` connections.

    Parameters
    ----------
    rcfg : dict
        Per-prospect routine config for ``connection_sync`` — typically
        ``routines_config.load_config()["per_prospect"]["connection_sync"]``.
    probe : SyncProbe | None
        Callable invoked once per due row; returns True / False / error
        string. Defaults to the live LinkedIn probe.
    rate_limit_check : callable | None
        Optional pre-check (e.g. ``lambda: rate_limit("profile_view",
        record=False)``). Returning a non-None value stops the sweep early.
        Defaults to ``None`` (no pre-check).
    now : datetime | None
        Frozen "now" for deterministic tests. Defaults to UTC now.

    Returns
    -------
    SyncSweepResult
    """
    policy = _policy_from_config(rcfg)
    now = now or datetime.now(timezone.utc)
    probe_fn = probe or _default_live_probe()

    data = _load_connections()
    rows = data.get("connections") or []
    result = SyncSweepResult()

    started_iso = _utcnow_iso()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("connection_status") != "pending":
            continue
        if not _row_due(row, now=now):
            result.skipped_not_due += 1
            continue

        if rate_limit_check is not None:
            err = rate_limit_check()
            if err:
                result.skipped_rate_limited += 1
                result.rate_limit_message = err
                logger.info(
                    "sync sweep skipping due to rate limit: %s (prospect=%s)",
                    err,
                    row.get("prospect_id"),
                )
                # Daily cap: stop iterating, don't bump backoff for skipped rows.
                break

        profile_url = (row.get("profile_url") or "").strip()
        if not profile_url:
            logger.warning(
                "sync sweep: skipping row with no profile_url (prospect=%s)",
                row.get("prospect_id"),
            )
            continue

        result.checked += 1
        try:
            res = await probe_fn(profile_url)
        except Exception as exc:  # pragma: no cover - defensive
            res = f"error: {exc}"

        if isinstance(res, str):
            # Probe returned an error string.
            _record_error(
                row, policy=policy, rcfg=rcfg, now=now, error=res
            )
            result.errors.append(
                {"prospect_id": row.get("prospect_id"), "error": res}
            )
            _append_jsonl(
                ACTIONS_LOG,
                {
                    "action": "connection_sync_error",
                    "prospect_id": row.get("prospect_id"),
                    "profile_url": profile_url,
                    "error": res,
                    "timestamp": _utcnow_iso(),
                },
            )
            continue

        if res is True:
            previous_status = row.get("connection_status")
            row["connection_status"] = "connected"
            row["connected_at"] = _utcnow_iso()
            _record_success(row)
            result.promoted.append(
                {
                    "prospect_id": row.get("prospect_id"),
                    "name": row.get("name"),
                    "profile_url": profile_url,
                    "previous_status": previous_status,
                }
            )
            _append_jsonl(
                ACTIONS_LOG,
                {
                    "action": "connection_accepted_sync",
                    "prospect_id": row.get("prospect_id"),
                    "profile_url": profile_url,
                    "timestamp": _utcnow_iso(),
                },
            )
            logger.info(
                "sync sweep promoted prospect_id=%s",
                row.get("prospect_id"),
            )
        else:
            _record_no_change(row, policy=policy, rcfg=rcfg, now=now)
            result.still_pending += 1

    _save_connections(data)

    # Per-sweep run-log line so the dashboard can show a one-row summary.
    _append_jsonl(
        RUNS_LOG,
        {
            "routine_id": "connection_sync",
            "kind": "sync_sweep",
            "status": "success" if not result.errors else "partial",
            "started_at": started_iso,
            "finished_at": _utcnow_iso(),
            **{k: v for k, v in result.to_log_row().items() if k != "kind"},
        },
    )

    return result


def run_sync_sweep_sync(
    rcfg: dict[str, Any],
    **kwargs: Any,
) -> SyncSweepResult:
    """Convenience wrapper to call from synchronous test code."""
    return asyncio.run(run_sync_sweep(rcfg, **kwargs))


__all__ = [
    "SyncProbe",
    "SyncSweepResult",
    "run_sync_sweep",
    "run_sync_sweep_sync",
]
