"""Tests for tools/outreach_config.py and the tools/validate_outreach_config.py CLI.

These are pure-filesystem/schema checks — no MCP server, no LinkedIn, no mocks
required beyond tmp_path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from outreach_config import (
    atomic_write_json,
    validate_conversation_planner_config,
    validate_persona_config,
)

CORE_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATE_CLI = CORE_ROOT / "tools" / "validate_outreach_config.py"


# ── validate_persona_config ─────────────────────────────────────────────────


def test_validate_persona_config_accepts_full_valid_doc():
    doc = {
        "persona": {
            "name": "Ada",
            "role": "engineer",
            "organization": "Acme",
            "specialization": "distributed systems",
        },
        "organization": {"description": "We build things."},
    }
    assert validate_persona_config(doc) is None


def test_validate_persona_config_accepts_partial_doc():
    assert validate_persona_config({"persona": {"name": "Ada"}}) is None
    assert validate_persona_config({}) is None


def test_validate_persona_config_rejects_non_dict():
    assert validate_persona_config([]) is not None


def test_validate_persona_config_rejects_unknown_key():
    err = validate_persona_config({"persona": {"nickname": "Ada"}})
    assert err is not None
    assert "unknown keys" in err


def test_validate_persona_config_rejects_non_string_value():
    err = validate_persona_config({"organization": {"description": 123}})
    assert err is not None
    assert "must be a string" in err


# ── validate_conversation_planner_config ────────────────────────────────────


def test_validate_planner_config_accepts_minimal_doc():
    assert validate_conversation_planner_config({}) is None
    assert validate_conversation_planner_config({"campaign": {"goal": "x"}}) is None


def test_validate_planner_config_rejects_persona_fields():
    err = validate_conversation_planner_config({"persona": {"name": "Ada"}})
    assert err is not None
    assert "persona.json" in err


def test_validate_planner_config_rejects_bad_char_limit():
    err = validate_conversation_planner_config(
        {"message_rules": {"connection_note_char_limit": -1}}
    )
    assert err is not None
    assert "connection_note_char_limit" in err


def test_validate_planner_config_rejects_bad_style_example():
    err = validate_conversation_planner_config(
        {"message_rules": {"style_examples": [{"label": "no reply"}]}}
    )
    assert err is not None
    assert "reply" in err


def test_validate_planner_config_accepts_valid_style_example():
    cfg = {
        "message_rules": {
            "style_examples": [{"reply": "Sure, happy to chat.", "label": "intro"}]
        }
    }
    assert validate_conversation_planner_config(cfg) is None


# ── atomic_write_json ────────────────────────────────────────────────────────


def test_atomic_write_json_roundtrip(tmp_path: Path):
    target = tmp_path / "config" / "persona.json"
    atomic_write_json(target, {"persona": {"name": "Ada"}})
    assert json.loads(target.read_text()) == {"persona": {"name": "Ada"}}
    # no leftover temp files
    assert list(target.parent.glob(".tmp_*")) == []


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE_CLI), *args],
        cwd=CORE_ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_validates_bundled_examples():
    result = _run_cli(
        "--persona",
        str(CORE_ROOT / "outreach" / "config" / "persona.json.example"),
        "--planner",
        str(CORE_ROOT / "outreach" / "config" / "conversation_planner.json.example"),
    )
    assert result.returncode == 0, result.stderr
    assert "ok:" in result.stdout


def test_cli_reports_error_and_exits_nonzero(tmp_path: Path):
    bad = tmp_path / "persona.json"
    bad.write_text(json.dumps({"persona": {"nickname": "Ada"}}))
    result = _run_cli("--persona", str(bad))
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_cli_reports_missing_file(tmp_path: Path):
    result = _run_cli("--persona", str(tmp_path / "missing.json"))
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_cli_requires_at_least_one_flag():
    result = _run_cli()
    assert result.returncode != 0
