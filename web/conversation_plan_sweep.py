"""
Per-prospect ``conversation-planner`` sweep.

Walks ``connections.json`` rows that are actionable for outreach planning
(``connection_status`` ``connected``), and for each row whose
``plan_backoff`` is due, dispatches a fresh ``claude -p`` invocation that
runs the ``conversation-planner`` skill in single-prospect mode.

Each prospect's run uses a tight context window (one prospect's id + skill
prose) instead of the previous batch mode that walked every connection in a
single Claude call. See
``docs/designs/per-connection-routines-with-backoff-design.md``.

The sweep guarantees:

- One outbound action per prospect per run (per-prospect ``asyncio.Lock``).
- Daily cap awareness: if ``rate_limit_check`` would deny ``dm``, the sweep
  stops issuing new dispatches without bumping backoff on skipped rows.
- No silent state corruption on ``claude -p`` failures: tool errors apply
  the jittered backoff curve but never advance ``connection_status``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from web.dashboard_data import _atomic_write_json, _read_json, outreach_base
from web.routine_backoff import (
    BackoffPolicy,
    PLAN_DEFAULT,
    apply_result,
    is_due,
    reschedule_to_window,
)

logger = logging.getLogger("web.conversation_plan_sweep")

CONNECTIONS_FILE = "connections.json"
ACTIONS_LOG = "logs/actions.jsonl"
RUNS_LOG = "logs/routine_runs.jsonl"
TICKS_LOG = "logs/routine_ticks.jsonl"

TERMINAL_OUTREACH_STAGES = frozenset({"ended", "dead"})
TERMINAL_CONNECTION_STATUSES = frozenset({"ended"})
SKIP_CONNECTION_STATUSES = frozenset({"pending", "ended"})

PlanRunner = Callable[[str], Awaitable["PlanRunResult"]]
"""Async callable that runs ``conversation-planner`` for one prospect_id."""


@dataclass(frozen=True)
class PlanRunResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    error: str | None = None


@dataclass
class PlanSweepResult:
    actionable: int = 0
    dispatched: int = 0
    sent: list[dict[str, Any]] = field(default_factory=list)
    ended: list[dict[str, Any]] = field(default_factory=list)
    no_action: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped_rate_limited: int = 0
    skipped_not_due: int = 0
    skipped_in_progress: int = 0
    rate_limit_message: str | None = None

    def to_log_row(self) -> dict[str, Any]:
        return {
            "actionable": self.actionable,
            "dispatched": self.dispatched,
            "sent": [s["prospect_id"] for s in self.sent],
            "ended": [e["prospect_id"] for e in self.ended],
            "no_action": [n["prospect_id"] for n in self.no_action],
            "errors": self.errors,
            "skipped_rate_limited": self.skipped_rate_limited,
            "skipped_not_due": self.skipped_not_due,
            "skipped_in_progress": self.skipped_in_progress,
            "rate_limit_message": self.rate_limit_message,
        }


# ── Per-prospect locks ────────────────────────────────────────────────────────

_PROSPECT_LOCKS: dict[str, asyncio.Lock] = {}


def _prospect_lock(prospect_id: str) -> asyncio.Lock:
    lock = _PROSPECT_LOCKS.get(prospect_id)
    if lock is None:
        lock = asyncio.Lock()
        _PROSPECT_LOCKS[prospect_id] = lock
    return lock


# ── Paths / IO helpers ────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _connections_path() -> Path:
    return outreach_base() / CONNECTIONS_FILE


def _conversation_path(prospect_id: str) -> Path:
    return outreach_base() / "conversations" / f"{prospect_id}.json"


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


def _read_conversation_snapshot(prospect_id: str) -> dict[str, Any] | None:
    return _read_json(_conversation_path(prospect_id), None)


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Default Claude runner (subprocess) ────────────────────────────────────────


def _default_runner() -> PlanRunner:
    """Default plan runner: shells out via ``web.skill_runner.run_skill_prompt``.

    Imported lazily so unit tests can supply a mock without claude on PATH.
    """

    async def _run(prospect_id: str) -> PlanRunResult:
        # Lazy import to avoid claude CLI requirement in tests.
        from web.skill_runner import run_skill_prompt

        prompt = (
            f'Run the conversation-planner skill for prospect_id="{prospect_id}". '
            "Operate in single-prospect mode (Phases A → D as documented). "
            "Do not enumerate any other prospects."
        )
        result = await asyncio.to_thread(run_skill_prompt, prompt)
        return PlanRunResult(
            ok=result.ok,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            error=result.error,
        )

    return _run


# ── Classification ────────────────────────────────────────────────────────────


def _classify_outcome(
    *,
    prospect_id: str,
    started_at: datetime,
    run_result: PlanRunResult,
    snapshot_before: dict[str, Any] | None,
    snapshot_after: dict[str, Any] | None,
    row_after: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Reduce a run + before/after snapshots to a backoff curve result.

    Returns ``(result, detail)`` where ``result`` is one of
    ``"success" | "no_change" | "tool_error"`` and ``detail`` is an optional
    short tag (``"sent"``, ``"ended"``, ``"no_action"``).
    """
    if not run_result.ok:
        return "tool_error", run_result.error or "claude exit nonzero"

    if isinstance(row_after, dict) and (
        row_after.get("connection_status") in TERMINAL_CONNECTION_STATUSES
    ):
        return "success", "ended"

    if isinstance(snapshot_after, dict):
        stage = snapshot_after.get("outreach_stage")
        if isinstance(stage, str) and stage in TERMINAL_OUTREACH_STAGES:
            return "success", "ended"

        ts = _parse_iso(snapshot_after.get("last_action_timestamp"))
        if ts is not None and ts >= started_at:
            return "success", "sent"

        before_ts = _parse_iso(
            (snapshot_before or {}).get("last_action_timestamp")
        )
        if (
            ts is not None
            and before_ts is not None
            and ts > before_ts
        ):
            return "success", "sent"

    return "no_change", "no_action"


def _record_outcome(
    row: dict[str, Any],
    *,
    result: str,
    policy: BackoffPolicy,
    rcfg: dict[str, Any],
    now: datetime,
    error: str | None,
) -> None:
    next_backoff = apply_result(
        row.get("plan_backoff"),
        policy=policy,
        result=result,  # type: ignore[arg-type]
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
        row.pop("plan_backoff", None)
    else:
        row["plan_backoff"] = next_backoff


def _policy_from_config(rcfg: dict[str, Any]) -> BackoffPolicy:
    return BackoffPolicy.from_config(rcfg.get("backoff"), defaults=PLAN_DEFAULT)


def _actionable(row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("connection_status") in SKIP_CONNECTION_STATUSES:
        return False
    if not row.get("prospect_id"):
        return False
    if not row.get("profile_url"):
        return False
    return True


# ── Main sweep ────────────────────────────────────────────────────────────────


async def run_plan_sweep(
    rcfg: dict[str, Any],
    *,
    runner: PlanRunner | None = None,
    rate_limit_check: Callable[[], str | None] | None = None,
    now: datetime | None = None,
) -> PlanSweepResult:
    """Run one pass over all actionable connections.

    See module docstring for behaviour. Returns a :class:`PlanSweepResult`.
    """
    policy = _policy_from_config(rcfg)
    now = now or _utcnow()
    runner_fn = runner or _default_runner()

    data = _load_connections()
    rows: list[dict[str, Any]] = data.get("connections") or []
    result = PlanSweepResult()

    started_iso = _utcnow_iso()
    for row in rows:
        if not _actionable(row):
            continue
        result.actionable += 1

        if not is_due(row.get("plan_backoff"), now=now):
            result.skipped_not_due += 1
            continue

        prospect_id = str(row.get("prospect_id") or "")
        lock = _prospect_lock(prospect_id)
        if lock.locked():
            result.skipped_in_progress += 1
            logger.info(
                "plan sweep: prospect %s already running, skipping", prospect_id
            )
            continue

        if rate_limit_check is not None:
            err = rate_limit_check()
            if err:
                result.skipped_rate_limited += 1
                result.rate_limit_message = err
                logger.info(
                    "plan sweep skipping due to rate limit: %s (prospect=%s)",
                    err,
                    prospect_id,
                )
                break

        async with lock:
            snapshot_before = _read_conversation_snapshot(prospect_id)
            started_at = _utcnow()
            try:
                run_result = await runner_fn(prospect_id)
            except Exception as exc:  # pragma: no cover - defensive
                run_result = PlanRunResult(
                    ok=False,
                    stdout="",
                    stderr=str(exc),
                    returncode=-1,
                    error=f"runner exception: {exc}",
                )

            # Conversation file may have been rewritten by the skill via MCP.
            snapshot_after = _read_conversation_snapshot(prospect_id)
            # The connection row in memory may be stale if the planner ended
            # the sequence; re-read the file so terminal status sticks.
            refreshed = _load_connections().get("connections") or []
            row_after = next(
                (
                    r
                    for r in refreshed
                    if isinstance(r, dict)
                    and r.get("prospect_id") == prospect_id
                ),
                None,
            )

            outcome, detail = _classify_outcome(
                prospect_id=prospect_id,
                started_at=started_at,
                run_result=run_result,
                snapshot_before=snapshot_before,
                snapshot_after=snapshot_after,
                row_after=row_after,
            )

            # Mutate the row we are about to persist. Prefer the freshest row
            # from disk if available so we don't clobber MCP-side writes.
            target_row = row_after if row_after is not None else row
            _record_outcome(
                target_row,
                result=outcome,
                policy=policy,
                rcfg=rcfg,
                now=_utcnow(),
                error=run_result.error if outcome == "tool_error" else None,
            )

            result.dispatched += 1
            entry = {
                "prospect_id": prospect_id,
                "detail": detail,
            }
            if outcome == "tool_error":
                entry["error"] = run_result.error
                result.errors.append(entry)
            elif detail == "ended":
                result.ended.append(entry)
            elif detail == "sent":
                result.sent.append(entry)
            else:
                result.no_action.append(entry)

            _append_jsonl(
                ACTIONS_LOG,
                {
                    "action": "conversation_plan_run",
                    "prospect_id": prospect_id,
                    "outcome": outcome,
                    "detail": detail,
                    "error": run_result.error,
                    "returncode": run_result.returncode,
                    "timestamp": _utcnow_iso(),
                },
            )

            # Persist any backoff mutation we made (and pick up any row state
            # changes the planner made between the time we loaded ``data``
            # and now). We round-trip through ``_load_connections`` so we
            # update only the matching row.
            current = _load_connections()
            replaced = False
            for i, r in enumerate(current.get("connections") or []):
                if (
                    isinstance(r, dict)
                    and r.get("prospect_id") == prospect_id
                ):
                    current["connections"][i] = target_row
                    replaced = True
                    break
            if not replaced and isinstance(current.get("connections"), list):
                current["connections"].append(target_row)
            _save_connections(current)

    # Split run-log lines: actual dispatches (or rate-limited / error ticks)
    # land in routine_runs.jsonl which drives the dashboard run history;
    # purely-skipped ticks land in routine_ticks.jsonl for diagnostics so
    # the operator can still see the scheduler is healthy without polluting
    # the run history.
    did_work = (
        result.dispatched > 0
        or result.errors
        or result.skipped_rate_limited > 0
    )
    log_row: dict[str, Any] = {
        "routine_id": "conversation_plan",
        "kind": "plan_sweep",
        "status": ("success" if not result.errors else "partial")
        if did_work
        else "skipped",
        "started_at": started_iso,
        "finished_at": _utcnow_iso(),
        **result.to_log_row(),
    }
    if not did_work:
        log_row["reason"] = "all_rows_in_backoff"
    _append_jsonl(RUNS_LOG if did_work else TICKS_LOG, log_row)

    return result


def run_plan_sweep_sync(rcfg: dict[str, Any], **kwargs: Any) -> PlanSweepResult:
    """Convenience wrapper for synchronous test code."""
    return asyncio.run(run_plan_sweep(rcfg, **kwargs))


__all__ = [
    "PlanRunResult",
    "PlanSweepResult",
    "PlanRunner",
    "run_plan_sweep",
    "run_plan_sweep_sync",
]
