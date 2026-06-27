"""
Local regression: Claude CLI (``claude -p``) + ``tools/mock.py`` + transition specs.

Requires ``claude`` on PATH and auth for the Claude Code CLI; otherwise scenario
tests skip. Tier-0 schedule tests: ``tests/test_schedule_meeting.py``.

``happy_path`` expects ``ended_reason: call_scheduled`` and ``meeting_link`` after the
scripted email reply (see ``docs/designs/schedule-meeting-mcp-and-regression-design.md``).
The harness applies ``schedule_meeting`` automatically when the mock thread contains an
email but the planner skipped booking; set ``REGRESSION_APPLY_SCHEDULE=0`` to disable.

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
    get_server_module,
    run_scenario,
)
from outreach.mock.fixtures_loader import list_case_ids  # noqa: E402

ALL_MOCK_CASES = list_case_ids()


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
    # Hard guard: regression must never talk to real LinkedIn.
    # ``testing/tools/server.py::_mock_mcp_enabled`` is the single source of truth
    # for which I/O backend the MCP server uses; if it returns False the
    # regression would silently drive the operator's live session.
    mod = get_server_module()
    assert mod._mock_mcp_enabled(), (
        "Regression must run with testing/tools/server.py::_mock_mcp_enabled() == True. "
        "Run `make -C testing regression` (sets OUTREACH_MOCK=1 automatically)."
    )
    run_scenario(case_id)
