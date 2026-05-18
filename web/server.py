#!/usr/bin/env python3
"""
FastAPI app for the LinkedIn outreach dashboard.

- GET /                    → dashboard (home)
- GET /dashboard.css, /dashboard.js
- GET /api/dashboard/*     → outreach data + routine config
- POST /api/dashboard/connections → send connection via Claude skill

Run with uvicorn (see Makefile ``make web``)::

    uvicorn web.server:app --host 127.0.0.1 --port 3847
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from web import dashboard_data, routine_scheduler, routines_config, skill_runner

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent

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


app = FastAPI(title="LinkedIn Outreach Dashboard", lifespan=lifespan)


def _static_file(name: str, media_type: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
async def index() -> FileResponse:
    return _static_file("dashboard.html", "text/html; charset=utf-8")


@app.get("/dashboard")
async def dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=302)


@app.get("/dashboard.css")
async def dashboard_css() -> FileResponse:
    return _static_file("dashboard.css", "text/css; charset=utf-8")


@app.get("/dashboard.js")
async def dashboard_js() -> FileResponse:
    return _static_file("dashboard.js", "application/javascript; charset=utf-8")


@app.get("/api/dashboard/health")
async def api_dashboard_health() -> JSONResponse:
    return JSONResponse(dashboard_data.get_health())


@app.get("/api/dashboard/connections")
async def api_dashboard_connections() -> JSONResponse:
    return JSONResponse(dashboard_data.get_connections())


class ConnectionRequest(BaseModel):
    profile_url: str = Field(..., min_length=8)


@app.post("/api/dashboard/connections")
async def api_dashboard_add_connection(body: ConnectionRequest) -> JSONResponse:
    result = await asyncio.to_thread(
        skill_runner.run_send_connection, body.profile_url.strip()
    )
    payload = result.to_dict()
    if result.ok:
        return JSONResponse(payload)
    return JSONResponse(status_code=500, content=payload)


@app.get("/api/dashboard/routines")
async def api_dashboard_routines() -> JSONResponse:
    return JSONResponse(dashboard_data.get_routines())


@app.get("/api/dashboard/routines/config")
async def api_dashboard_routines_config() -> JSONResponse:
    return JSONResponse(routines_config.get_routines_for_api())


class RoutinesConfigBody(BaseModel):
    routines: list[dict] = Field(default_factory=list)


@app.put("/api/dashboard/routines/config")
async def api_dashboard_routines_config_put(body: RoutinesConfigBody) -> JSONResponse:
    try:
        data = routines_config.upsert_routines(body.routines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(data)


@app.post("/api/dashboard/routines/{routine_id}/run")
async def api_dashboard_routine_run_now(routine_id: str) -> JSONResponse:
    cfg = routines_config.load_config()
    routine = next(
        (r for r in cfg.get("routines") or [] if r.get("id") == routine_id),
        None,
    )
    if not routine:
        raise HTTPException(status_code=404, detail="routine not found")
    skill = routine.get("skill") or ""
    started = datetime.now(timezone.utc).isoformat()
    result = await asyncio.to_thread(skill_runner.run_named_skill, skill)
    finished = datetime.now(timezone.utc).isoformat()
    status = "success" if result.ok else "failed"
    routines_config.append_run_log(
        routine_id=routine_id,
        skill=skill,
        status=status,
        started_at=started,
        finished_at=finished,
        error=result.error,
        stdout_tail=result.stdout,
    )
    routines_config.update_routine_after_run(
        routine_id, status=status, error=result.error
    )
    return JSONResponse(result.to_dict(), status_code=200 if result.ok else 500)


@app.get("/api/dashboard/execution-history")
async def api_dashboard_execution_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_execution_history(limit=limit, offset=offset))


@app.get("/api/dashboard/meetings")
async def api_dashboard_meetings() -> JSONResponse:
    return JSONResponse(dashboard_data.get_meetings())


@app.get("/api/dashboard/summary")
async def api_dashboard_summary() -> JSONResponse:
    return JSONResponse(dashboard_data.get_summary())


@app.get("/api/dashboard/skills")
async def api_dashboard_skills() -> JSONResponse:
    return JSONResponse({"skills": sorted(skill_runner.ALLOWED_SKILLS)})


def main() -> None:
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "3847"))
    print(f"[web] http://{host}:{port}/  (repo {REPO_ROOT})")
    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
