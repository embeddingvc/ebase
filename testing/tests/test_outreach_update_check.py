"""Tests for bin/outreach-update-check's SERVICE_DOWN health probe."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = CORE_ROOT / "bin" / "outreach-update-check"


def _fake_curl(tmp_path: Path, *, exit_code: int) -> Path:
    """Write a stub `curl` on PATH that always exits with `exit_code`."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f"#!/usr/bin/env bash\nexit {exit_code}\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def test_service_down_printed_when_curl_fails(tmp_path: Path) -> None:
    fake_bin = _fake_curl(tmp_path, exit_code=1)
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    result = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "OUTREACH_REPO_ROOT": str(empty_repo),
            "OUTREACH_STATE_DIR": str(tmp_path / "state"),
        },
    )

    assert "SERVICE_DOWN browser" in result.stdout
    assert "SERVICE_DOWN cron" in result.stdout


def test_no_service_down_when_curl_succeeds(tmp_path: Path) -> None:
    fake_bin = _fake_curl(tmp_path, exit_code=0)
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    result = subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "OUTREACH_REPO_ROOT": str(empty_repo),
            "OUTREACH_STATE_DIR": str(tmp_path / "state"),
        },
    )

    assert "SERVICE_DOWN" not in result.stdout


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_bare_with_version(parent: Path, name: str, version: str) -> Path:
    """Create a bare repo whose main branch has VERSION=<version>."""
    bare = parent / f"{name}-bare.git"
    _git("init", "--bare", "-b", "main", str(bare), cwd=parent)

    work = parent / f"{name}-work"
    work.mkdir()
    _git("init", "-b", "main", cwd=work)
    _git("config", "user.email", "test@example.com", cwd=work)
    _git("config", "user.name", "Test", cwd=work)
    (work / "VERSION").write_text(version)
    _git("add", "VERSION", cwd=work)
    _git("commit", "-m", "version", cwd=work)
    _git("push", str(bare), "main", cwd=work)
    return bare


def test_prefers_upstream_remote_over_stale_origin(tmp_path: Path) -> None:
    """A configured `upstream` remote must win over a stale `origin` fork."""
    fake_bin = _fake_curl(tmp_path, exit_code=0)

    origin_bare = _init_bare_with_version(tmp_path, "origin", "1.0.0.15")
    upstream_bare = _init_bare_with_version(tmp_path, "upstream", "1.0.0.20")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "VERSION").write_text("1.0.0.19")
    _git("add", "VERSION", cwd=repo)
    _git("commit", "-m", "version", cwd=repo)
    _git("remote", "add", "origin", str(origin_bare), cwd=repo)
    _git("remote", "add", "upstream", str(upstream_bare), cwd=repo)

    result = subprocess.run(
        [str(SCRIPT), "--force"],
        capture_output=True,
        text=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
            "OUTREACH_REPO_ROOT": str(repo),
            "OUTREACH_STATE_DIR": str(tmp_path / "state"),
        },
    )

    # A stale origin would make this look UP_TO_DATE at 1.0.0.19; picking
    # upstream must surface the real 1.0.0.20 update instead.
    assert "UPGRADE_AVAILABLE 1.0.0.19 1.0.0.20" in result.stdout
