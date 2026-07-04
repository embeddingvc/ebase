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
