"""
Background asyncio scheduler.

Two execution modes selected by the ``scheduler_kind`` field of
``dashboard_routines.json`` (see ``web.routines_config``):

- ``"loop"`` (default, legacy): runs each routine row's Claude skill on
  interval via ``run_named_skill`` — the skill loops over connections inside
  one Claude call.
- ``"per_prospect"`` (new): the scheduler runs typed sweeps directly.
  ``connection_sync`` is a deterministic Python sweep (no LLM);
  ``conversation_plan`` dispatches a fresh ``claude -p`` per actionable
  prospect with per-row exponential backoff and daily rate-limit awareness.

See ``docs/designs/per-connection-routines-with-backoff-design.md``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web import routines_config
from web.skill_runner import run_named_skill

logger = logging.getLogger("web.routine_scheduler")

TICK_SECONDS = 30
_running_locks: dict[str, asyncio.Lock] = {}

# Per-sweep locks for per_prospect mode so a long sweep cannot stack.
# Created lazily so module import never requires a running event loop.
_sweep_locks: dict[str, asyncio.Lock] = {}


def _get_sweep_lock(kind: str) -> asyncio.Lock:
    lock = _sweep_locks.get(kind)
    if lock is None:
        lock = asyncio.Lock()
        _sweep_locks[kind] = lock
    return lock

# Tracks last sweep timestamps in per_prospect mode. The sweep cadence is the
# floor on how often the sweep can possibly run — individual prospects still
# obey their own ``sync_backoff`` / ``plan_backoff`` records.
_last_sweep_at: dict[str, datetime] = {}


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _due(routine: dict[str, Any]) -> bool:
    if not routine.get("active"):
        return False
    if not routines_config.in_active_window(routine):
        return False
    last = _parse_iso(routine.get("last_run_at"))
    if last is None:
        return True
    interval_min = int(routine.get("interval_minutes") or 60)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= interval_min * 60


async def _run_one(routine: dict[str, Any]) -> None:
    rid = routine["id"]
    skill = routine["skill"]
    lock = _running_locks.setdefault(rid, asyncio.Lock())
    if lock.locked():
        logger.info("routine %s already running, skip", rid)
        return
    async with lock:
        started = datetime.now(timezone.utc).isoformat()
        logger.info("routine %s starting skill=%s", rid, skill)
        result = await asyncio.to_thread(run_named_skill, skill)
        finished = datetime.now(timezone.utc).isoformat()
        status = "success" if result.ok else "failed"
        routines_config.append_run_log(
            routine_id=rid,
            skill=skill,
            status=status,
            started_at=started,
            finished_at=finished,
            error=result.error,
            stdout_tail=result.stdout,
        )
        routines_config.update_routine_after_run(
            rid, status=status, error=result.error
        )
        if result.ok:
            logger.info("routine %s finished ok", rid)
        else:
            logger.warning("routine %s failed: %s", rid, result.error)


# ── per_prospect mode ─────────────────────────────────────────────────────────


# Cadence at which the scheduler is *allowed* to invoke a sweep. Individual
# rows still throttle themselves via their per-row backoff records.
_PER_PROSPECT_SWEEP_INTERVAL_SECONDS = int(
    os.environ.get("PER_PROSPECT_SWEEP_INTERVAL_SECONDS", "60")
)


def _per_prospect_due(kind: str, now: datetime) -> bool:
    last = _last_sweep_at.get(kind)
    if last is None:
        return True
    return (now - last).total_seconds() >= _PER_PROSPECT_SWEEP_INTERVAL_SECONDS


def _rate_limit_check_factory(category: str):
    """Return ``lambda: rate_limit(category, record=False)`` or None.

    Importing ``rate_limits`` requires ``tools/`` on ``sys.path``; we add it
    lazily so unit tests that don't need the live module are unaffected.
    """

    def _ensure_tools_path() -> None:
        tools_dir = Path(__file__).resolve().parent.parent / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))

    def _check() -> str | None:
        try:
            _ensure_tools_path()
            from rate_limits import rate_limit  # type: ignore[import-not-found]
        except Exception:
            return None  # If rate limits aren't importable, don't gate.
        return rate_limit(category, record=False)

    return _check


async def _run_sync_sweep_routine(rcfg: dict[str, Any]) -> None:
    """Wrapper to call ``connection_sync_sweep.run_sync_sweep`` with logging."""
    kind = routines_config.ROUTINE_KIND_CONNECTION_SYNC
    lock = _get_sweep_lock(kind)
    if lock.locked():
        logger.info("sync sweep already running, skip")
        return
    async with lock:
        if not rcfg.get("active"):
            return
        if not routines_config.in_active_window(rcfg):
            return
        from web.connection_sync_sweep import run_sync_sweep

        _last_sweep_at[kind] = datetime.now(timezone.utc)
        try:
            await run_sync_sweep(
                rcfg,
                rate_limit_check=_rate_limit_check_factory("profile_view"),
            )
        except Exception:
            logger.exception("connection sync sweep failed")


async def _run_plan_sweep_routine(rcfg: dict[str, Any]) -> None:
    """Wrapper to call ``conversation_plan_sweep.run_plan_sweep`` with logging."""
    kind = routines_config.ROUTINE_KIND_CONVERSATION_PLAN
    lock = _get_sweep_lock(kind)
    if lock.locked():
        logger.info("plan sweep already running, skip")
        return
    async with lock:
        if not rcfg.get("active"):
            return
        if not routines_config.in_active_window(rcfg):
            return
        from web.conversation_plan_sweep import run_plan_sweep

        _last_sweep_at[kind] = datetime.now(timezone.utc)
        try:
            await run_plan_sweep(
                rcfg,
                rate_limit_check=_rate_limit_check_factory("dm"),
            )
        except Exception:
            logger.exception("conversation plan sweep failed")


async def _tick_per_prospect(cfg: dict[str, Any]) -> None:
    pp = cfg.get("per_prospect") or {}
    now = datetime.now(timezone.utc)

    sync_cfg = pp.get(routines_config.ROUTINE_KIND_CONNECTION_SYNC) or {}
    if _per_prospect_due(routines_config.ROUTINE_KIND_CONNECTION_SYNC, now):
        asyncio.create_task(_run_sync_sweep_routine(sync_cfg))

    plan_cfg = pp.get(routines_config.ROUTINE_KIND_CONVERSATION_PLAN) or {}
    if _per_prospect_due(routines_config.ROUTINE_KIND_CONVERSATION_PLAN, now):
        asyncio.create_task(_run_plan_sweep_routine(plan_cfg))


async def _tick_loop(cfg: dict[str, Any]) -> None:
    for routine in cfg.get("routines") or []:
        if _due(routine):
            asyncio.create_task(_run_one(routine))


async def _tick() -> None:
    cfg = routines_config.load_config()
    kind = routines_config._coerce_scheduler_kind(cfg.get("scheduler_kind"))
    if kind == routines_config.SCHEDULER_KIND_PER_PROSPECT:
        await _tick_per_prospect(cfg)
    else:
        await _tick_loop(cfg)


async def scheduler_loop(stop: asyncio.Event) -> None:
    logger.info("routine scheduler started (tick=%ss)", TICK_SECONDS)
    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("routine scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("routine scheduler stopped")
