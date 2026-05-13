#!/usr/bin/env python3
"""
FastAPI app for the Claude cowork-style web UI.

- GET /              → index.html
- GET /styles.css, /app.js → static assets
- POST /api/claude   → run ``claude -p`` in the repository root

Run with uvicorn (see Makefile ``make web``)::

    uvicorn web.server:app --host 127.0.0.1 --port 3847

Env: ``WEB_HOST``, ``WEB_PORT`` (Makefile passes these to uvicorn), ``CLAUDE_WEB_TIMEOUT_SEC``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent

PERMISSION_MODES = frozenset(
    {"dontAsk", "acceptEdits", "auto", "default", "bypassPermissions", "plan"}
)

app = FastAPI(title="LinkedIn Outreach — Claude cowork")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/styles.css")
async def styles_css() -> FileResponse:
    path = WEB_DIR / "styles.css"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path,
        media_type="text/css; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/app.js")
async def app_js() -> FileResponse:
    path = WEB_DIR / "app.js"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


class ClaudeRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    permissionMode: str = "dontAsk"


@app.post("/api/claude")
async def api_claude(body: ClaudeRequest) -> JSONResponse:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    perm = body.permissionMode.strip()
    if perm not in PERMISSION_MODES:
        raise HTTPException(status_code=400, detail="invalid permissionMode")

    cmd = ["claude", "-p", prompt, "--permission-mode", perm]

    env = os.environ.copy()
    home = env.get("HOME", "")
    env["PATH"] = f"{home}/.local/bin:{home}/.cargo/bin:{env.get('PATH', '')}"

    timeout = int(os.environ.get("CLAUDE_WEB_TIMEOUT_SEC", "600"))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error": "claude subprocess timeout"},
        )
    except FileNotFoundError:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "claude CLI not found on PATH"},
        )

    payload: dict[str, object] = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }
    if proc.returncode != 0:
        payload["error"] = f"claude exited with status {proc.returncode}"

    status = 200 if proc.returncode == 0 else 500
    return JSONResponse(status_code=status, content=payload)


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
