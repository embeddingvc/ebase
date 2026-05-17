"""
Local regression: Claude CLI (``claude -p``) + ``tools/mock.py`` + transition specs.

Requires ``claude`` on PATH and auth for the Claude Code CLI; otherwise scenario
tests skip. Tier-0 tests (JSON extract) always run.

Run: ``make regression`` or ``uv run pytest tests/test_regression_workflow.py -v``
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from outreach.regression_harness import (  # noqa: E402
    claude_cli_available,
    run_scenario,
)

ALL_MOCK_CASES = ["happy_path"]

@pytest.mark.local_regression
@pytest.mark.parametrize("case_id", ALL_MOCK_CASES)
def test_regression_mock_scenario(case_id: str) -> None:
    """
    Full loop: load ``TEST_CASES[case_id]``, call ``claude -p`` each round,
    assert transitions, apply mock send handlers.
    """
    if not claude_cli_available():
        pytest.skip(
            "Claude Code CLI not found in PATH. Install Claude Code and run "
            "`make claude-install` from the repo root. "
            "See docs/designs/outreach-workflow-regression-tests-design.md"
        )
    run_scenario(case_id)
