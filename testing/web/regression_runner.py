"""
Background regression runner for the dashboard's mock view.

Spawns ``pytest tests/test_regression_workflow.py`` as a subprocess with
``OUTREACH_MOCK=1`` (so ``tools/server.py::_mock_mcp_enabled()`` returns True
without touching the source) and streams stdout/stderr to a log file under
``outreach/mock/logs/regression.log``.

A single global ``RegressionState`` singleton is exposed so the FastAPI
endpoints can query status, start, and stop runs. The dashboard polls
``/api/mock/regression/status`` and renders a live log + progress while the
mock conversation panel watches ``mock_linkedin_sessions.json`` for new DM
turns.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web.dashboard_data import mock_base

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent

LOG_TAIL_LINES = 400  # ring buffer surfaced through the API
DEFAULT_CASE_ID = "happy_path"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RegressionState:
    """In-memory state of the most recent (or active) regression run.

    The dashboard treats this as a single-slot queue: only one run can be
    active at a time. Starting a new run while ``status == "running"`` is
    rejected with ``RegressionBusyError``.
    """

    status: str = "idle"  # idle | starting | running | passed | failed | error | cancelled
    case_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None
    log_path: str | None = None
    log_tail: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_TAIL_LINES))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "case_id": self.case_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "error": self.error,
            "log_path": self.log_path,
            "log_tail": list(self.log_tail),
        }


class RegressionBusyError(RuntimeError):
    """Raised when ``start()`` is called while a run is already active."""


class RegressionRunner:
    """Single-slot subprocess manager for the mock regression scenario.

    ``start(case_id)`` spawns ``uv run pytest tests/test_regression_workflow.py``
    with ``-k <case_id>`` so we can pivot between scripted scenarios without
    rewriting the harness. A reader thread tails stdout/stderr into a ring
    buffer so the dashboard can surface live progress without polling the file.
    """

    def __init__(self) -> None:
        self.state = RegressionState()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.state.to_dict()

    def start(self, case_id: str | None = None) -> dict[str, Any]:
        """Spawn the regression subprocess. Raises if one is already running."""
        cid = (case_id or DEFAULT_CASE_ID).strip() or DEFAULT_CASE_ID
        with self._lock:
            if self.state.status in ("starting", "running"):
                raise RegressionBusyError(
                    f"regression already {self.state.status} (case={self.state.case_id!r})"
                )
            log_path = self._prepare_log_file(cid)
            cmd = self._pytest_cmd(cid)
            env = self._subprocess_env()
            self.state = RegressionState(
                status="starting",
                case_id=cid,
                started_at=_now_iso(),
                log_path=str(log_path),
            )
            self.state.log_tail.append(f"$ {' '.join(cmd)}")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    bufsize=1,
                    start_new_session=True,
                )
            except FileNotFoundError as exc:
                self.state.status = "error"
                self.state.error = f"failed to spawn regression: {exc}"
                self.state.finished_at = _now_iso()
                return self.state.to_dict()

            self._proc = proc
            self.state.pid = proc.pid
            self.state.status = "running"
            self._reader = threading.Thread(
                target=self._reader_loop,
                args=(proc, log_path),
                name=f"regression-reader-{proc.pid}",
                daemon=True,
            )
            self._reader.start()
            return self.state.to_dict()

    def stop(self) -> dict[str, Any]:
        """Terminate the running subprocess (TERM, then KILL after grace)."""
        with self._lock:
            proc = self._proc
            if not proc or proc.poll() is not None:
                return self.state.to_dict()
            pid = proc.pid
            self.state.log_tail.append(f"-- stop requested (pid={pid}) --")

        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except OSError:
                pass

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()

        with self._lock:
            if self.state.status == "running":
                self.state.status = "cancelled"
                self.state.finished_at = _now_iso()
                self.state.exit_code = proc.returncode
            return self.state.to_dict()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _prepare_log_file(self, case_id: str) -> Path:
        log_dir = mock_base() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "regression.log"
        # Truncate so each run owns its own log; previous tails stay in the UI
        # ring buffer until a refresh.
        header = (
            f"# regression run case={case_id}  started_at={_now_iso()}\n"
        )
        log_path.write_text(header, encoding="utf-8")
        return log_path

    def _pytest_cmd(self, case_id: str) -> list[str]:
        return [
            "uv",
            "run",
            "pytest",
            "tests/test_regression_workflow.py",
            "-v",
            "-s",
            "--no-header",
            "-x",
            "-k",
            case_id,
        ]

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # Force mock backend in tools/server.py + dashboard_data so the harness
        # never accidentally drives a real LinkedIn session.
        env["OUTREACH_MOCK"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        # Ensure ``claude`` and ``uv`` resolve from common install dirs.
        home = env.get("HOME", "")
        env["PATH"] = (
            f"{home}/.local/bin:{home}/.cargo/bin:/opt/homebrew/bin:" + env.get("PATH", "")
        )
        return env

    def _reader_loop(self, proc: subprocess.Popen[str], log_path: Path) -> None:
        assert proc.stdout is not None
        try:
            with log_path.open("a", encoding="utf-8") as f:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    f.write(line + "\n")
                    f.flush()
                    with self._lock:
                        self.state.log_tail.append(line)
        except OSError as exc:
            with self._lock:
                self.state.log_tail.append(f"-- reader error: {exc} --")

        rc = proc.wait()
        with self._lock:
            self.state.finished_at = _now_iso()
            self.state.exit_code = rc
            if self.state.status == "running":
                self.state.status = "passed" if rc == 0 else "failed"
            if rc != 0 and not self.state.error:
                self.state.error = f"pytest exited with status {rc}"


# Module-level singleton consumed by FastAPI handlers. A fresh runner is fine
# because the dashboard process is single-instance; if we ever go multi-worker
# we'd swap this for a file-locked store.
runner = RegressionRunner()
