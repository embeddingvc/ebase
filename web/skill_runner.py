"""
Invoke installed Claude Code skills via ``claude -p`` (same stack as regression harness).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent

ALLOWED_SKILLS = frozenset(
    {
        "send-connection-request",
        "sync-pending-connections",
        "conversation-planner",
        "sync-planner-persona-from-linkedin",
        "reply-to-post",
    }
)


@dataclass
class SkillRunResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "error": self.error,
        }


def _claude_env() -> dict[str, str]:
    env = os.environ.copy()
    home = env.get("HOME", "")
    env["PATH"] = f"{home}/.local/bin:{home}/.cargo/bin:{env.get('PATH', '')}"
    return env


def run_skill_prompt(prompt: str, *, timeout_sec: int | None = None) -> SkillRunResult:
    """Run an arbitrary ``claude -p`` prompt from repo root."""
    timeout = timeout_sec or int(os.environ.get("CLAUDE_WEB_TIMEOUT_SEC", "600"))
    perm = os.environ.get("REGRESSION_CLAUDE_PERMISSION_MODE", "bypassPermissions").strip()
    model = os.environ.get("CLAUDE_MODEL", "haiku").strip()
    cmd = ["claude", "-p", prompt, "--model", model, "--permission-mode", perm]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_claude_env(),
        )
    except subprocess.TimeoutExpired:
        return SkillRunResult(
            ok=False,
            stdout="",
            stderr="",
            returncode=-1,
            error=f"claude subprocess timeout ({timeout}s)",
        )
    except FileNotFoundError:
        return SkillRunResult(
            ok=False,
            stdout="",
            stderr="",
            returncode=-1,
            error="claude CLI not found on PATH",
        )

    err = None
    if proc.returncode != 0:
        err = f"claude exited with status {proc.returncode}"
    return SkillRunResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
        error=err,
    )


def run_named_skill(skill: str) -> SkillRunResult:
    if skill not in ALLOWED_SKILLS:
        return SkillRunResult(
            ok=False,
            stdout="",
            stderr="",
            returncode=-1,
            error=f"skill not allowed: {skill}",
        )
    return run_skill_prompt(f"Run {skill} skill")


def run_send_connection(profile_url: str) -> SkillRunResult:
    url = profile_url.strip()
    if not url:
        return SkillRunResult(
            ok=False,
            stdout="",
            stderr="",
            returncode=-1,
            error="profile_url required",
        )
    return run_skill_prompt(
        f"Connect to {url} using the send-connection-request skill."
    )
