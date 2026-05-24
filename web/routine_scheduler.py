"""
Background asyncio scheduler: runs configured Claude skills on interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from web import routines_config
from web.skill_runner import run_named_skill

logger = logging.getLogger("web.routine_scheduler")

TICK_SECONDS = 30
_running_locks: dict[str, asyncio.Lock] = {}


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


async def _tick() -> None:
    data = routines_config.load_config()
    for routine in data.get("routines") or []:
        if _due(routine):
            asyncio.create_task(_run_one(routine))


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
