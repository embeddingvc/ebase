#!/usr/bin/env python3
"""
Minimal production scheduler server.

Runs the routine scheduler (``cron.routine_scheduler``) as a background task
and exposes a health endpoint so ``install.sh`` / operators can verify the
process is alive. The full web dashboard lives in ``testing/web/`` and is a
development/QA tool only.

- GET /health                → liveness + scheduler state
- GET /api/scheduler/status  → last routine runs/ticks from the logs

Run with uvicorn (see Makefile ``make cron`` or ``./install.sh``)::

    uvicorn cron.server:app --host 127.0.0.1 --port 3847
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from cron import routine_scheduler
from outreach.data_paths import outreach_base

REPO_ROOT = Path(__file__).resolve().parent.parent

_scheduler_stop: asyncio.Event | None = None
_scheduler_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_stop, _scheduler_task
    _scheduler_stop = asyncio.Event()
    _scheduler_task = asyncio.create_task(
        routine_scheduler.scheduler_loop(_scheduler_stop)
    )
    yield
    if _scheduler_stop:
        _scheduler_stop.set()
    if _scheduler_task:
        await _scheduler_task


app = FastAPI(title="ebase Cron", lifespan=lifespan)


def _scheduler_state() -> str:
    if _scheduler_task is None:
        return "not_started"
    if _scheduler_task.done():
        return "stopped"
    return "running"


@app.get("/health")
async def health() -> JSONResponse:
    state = _scheduler_state()
    return JSONResponse(
        {
            "ok": state == "running",
            "scheduler": state,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "data_root": str(outreach_base()),
        }
    )


def _tail_jsonl(path: Path, limit: int) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


@app.get("/api/scheduler/status")
async def scheduler_status() -> JSONResponse:
    """Recent routine activity: real runs plus heartbeat ticks."""
    base = outreach_base()
    return JSONResponse(
        {
            "scheduler": _scheduler_state(),
            "tick_seconds": routine_scheduler.TICK_SECONDS,
            "recent_runs": _tail_jsonl(base / "logs" / "routine_runs.jsonl", 20),
            "recent_ticks": _tail_jsonl(base / "logs" / "routine_ticks.jsonl", 20),
        }
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("WEB_HOST", os.environ.get("CRON_HOST", "127.0.0.1"))
    port = int(os.environ.get("WEB_PORT", os.environ.get("CRON_PORT", "3847")))
    print(f"[cron] http://{host}:{port}/health  (repo {REPO_ROOT})")
    uvicorn.run(
        "cron.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
