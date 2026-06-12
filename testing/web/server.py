#!/usr/bin/env python3
"""
FastAPI app for the LinkedIn outreach dashboard (development / QA tool).

- GET /                    → dashboard (home)
- GET /mock                → mock-scope view (regression runner + mock thread)
- GET /dashboard.css, /dashboard.js
- GET /api/dashboard/*     → outreach data + routine config
- POST /api/dashboard/connections → send connection via Claude skill

The routine scheduler does NOT run here — production scheduling lives in the
core ``cron/server.py`` process. This server is read-mostly plus manual
triggers (run-now, regression control).

Run with uvicorn (see ``testing/Makefile`` ``make web``)::

    uvicorn web.server:app --host 127.0.0.1 --port 3848

Documentation: ``testing/docs/web-dashboard.md``
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
TESTING_ROOT = WEB_DIR.parent
CORE_ROOT = TESTING_ROOT.parent

# Core repo root first (cron package, outreach.browser); testing root next
# (web package, outreach.mock namespace portion).
for _p in (str(CORE_ROOT), str(TESTING_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from cron import routines_config, skill_runner
from web import (
    dashboard_data,
    mock_conversation,
    regression_runner,
)

app = FastAPI(title="LinkedIn Outreach Dashboard (testing)")


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


@app.get("/mock")
async def mock_index() -> FileResponse:
    """Mock-scope dashboard view (regression runner + live mock thread).

    Same SPA as ``/`` — the JS bundle reads ``location.pathname`` to decide
    whether to call ``?scope=mock`` API endpoints and to surface the mock-only
    Conversation + Regression tabs.
    """
    return _static_file("dashboard.html", "text/html; charset=utf-8")


@app.get("/dashboard.css")
async def dashboard_css() -> FileResponse:
    return _static_file("dashboard.css", "text/css; charset=utf-8")


@app.get("/dashboard.js")
async def dashboard_js() -> FileResponse:
    return _static_file("dashboard.js", "application/javascript; charset=utf-8")


def _normalize_scope(scope: str | None) -> str | None:
    if scope is None:
        return None
    s = scope.strip().lower()
    if s in ("mock", "live"):
        return s
    if s in ("", "auto"):
        return None
    raise HTTPException(status_code=400, detail="scope must be 'mock' or 'live'")


@app.get("/api/dashboard/health")
async def api_dashboard_health(
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_health(_normalize_scope(scope)))


@app.get("/api/dashboard/connections")
async def api_dashboard_connections(
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_connections(_normalize_scope(scope)))


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
async def api_dashboard_routines(
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_routines(_normalize_scope(scope)))


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
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(
        dashboard_data.get_execution_history(
            limit=limit, offset=offset, scope=_normalize_scope(scope)
        )
    )


@app.get("/api/dashboard/meetings")
async def api_dashboard_meetings(
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_meetings(_normalize_scope(scope)))


@app.get("/api/dashboard/summary")
async def api_dashboard_summary(
    scope: str | None = Query(None),
) -> JSONResponse:
    return JSONResponse(dashboard_data.get_summary(_normalize_scope(scope)))


@app.get("/api/dashboard/skills")
async def api_dashboard_skills() -> JSONResponse:
    return JSONResponse({"skills": sorted(skill_runner.ALLOWED_SKILLS)})


# ── Mock-only endpoints ──────────────────────────────────────────────────────
#
# Backing the dashboard's mock view: live conversation thread + regression
# subprocess control. These never read ``outreach/`` so they're safe even when
# the operator is running live outreach in the same dashboard session.


@app.get("/api/mock/conversation")
async def api_mock_conversation() -> JSONResponse:
    return JSONResponse(mock_conversation.get_mock_conversations())


@app.get("/api/mock/regression/cases")
async def api_mock_regression_cases() -> JSONResponse:
    return JSONResponse(mock_conversation.list_test_cases())


class RegressionRunBody(BaseModel):
    case_id: str | None = Field(default=None)


@app.get("/api/mock/regression/status")
async def api_mock_regression_status() -> JSONResponse:
    return JSONResponse(regression_runner.runner.status())


@app.post("/api/mock/regression/run")
async def api_mock_regression_run(body: RegressionRunBody) -> JSONResponse:
    try:
        state = await asyncio.to_thread(
            regression_runner.runner.start, body.case_id
        )
    except regression_runner.RegressionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(state)


@app.post("/api/mock/regression/stop")
async def api_mock_regression_stop() -> JSONResponse:
    state = await asyncio.to_thread(regression_runner.runner.stop)
    return JSONResponse(state)


def main() -> None:
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "3848"))
    print(f"[web] http://{host}:{port}/  (testing root {TESTING_ROOT})")
    uvicorn.run(
        "web.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
