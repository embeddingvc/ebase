"""
Shared schema + write helpers for outreach/config/persona.json and
conversation_planner.json.

Single source of truth so the MCP server (tools/server.py), the standalone
validator CLI (tools/validate_outreach_config.py), and install.sh's tone
questionnaire (tools/setup_tone_examples.py) all agree on what a valid config
file looks like instead of each carrying its own copy that can drift.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

ALLOWED_PLANNER_PERSONA_KEYS = frozenset(
    {"name", "role", "organization", "specialization"}
)
ALLOWED_PLANNER_ORGANIZATION_KEYS = frozenset({"description"})


def atomic_write_json(path: Path, data: object) -> None:
    """Write JSON atomically via temp-file + rename so a crash cannot corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        Path(tmp).replace(path)
    except Exception:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
        raise


def validate_persona_config(data: dict) -> str | None:
    """
    Validate a full persona.json document: ``{"persona": {...}, "organization": {...}}``.

    Both top-level keys are optional; when present each must be an object
    containing only its allowed string fields. Returns an error string, or
    None when valid.
    """
    if not isinstance(data, dict):
        return "persona.json must be a JSON object"

    for top_key, allowed in (
        ("persona", ALLOWED_PLANNER_PERSONA_KEYS),
        ("organization", ALLOWED_PLANNER_ORGANIZATION_KEYS),
    ):
        node = data.get(top_key)
        if node is None:
            continue
        if not isinstance(node, dict):
            return f"{top_key} must be an object"
        bad = sorted(set(node) - allowed)
        if bad:
            return f"{top_key} has unknown keys: " + ", ".join(repr(k) for k in bad)
        for key, val in node.items():
            if not isinstance(val, str):
                return f"{top_key}.{key} must be a string"

    return None


def validate_conversation_planner_config(config: dict) -> str | None:
    """
    Validate a full conversation_planner.json document (campaign / rules / router).

    ``persona`` / ``organization`` are rejected here — those live in
    persona.json (see ``validate_persona_config``). Returns an error string,
    or None when valid.
    """
    if not isinstance(config, dict):
        return "config must be a JSON object"

    if "persona" in config or "organization" in config:
        return (
            "persona and organization are stored in persona.json; remove them "
            "from this payload"
        )

    for key in (
        "campaign",
        "conversation_end_goals",
        "message_rules",
        "router",
    ):
        if key in config and not isinstance(config[key], dict):
            return f"{key} must be an object"

    for key in ("connection_note_char_limit", "followup_char_limit"):
        value = (
            config.get("message_rules", {}).get(key)
            if isinstance(config.get("message_rules"), dict)
            else None
        )
        if value is not None and (not isinstance(value, int) or value <= 0):
            return f"message_rules.{key} must be a positive integer"

    rules = config.get("message_rules")
    if isinstance(rules, dict):
        guidelines = rules.get("tone_guidelines")
        if guidelines is not None and not isinstance(guidelines, str):
            return "message_rules.tone_guidelines must be a string"

        examples = rules.get("style_examples")
        if examples is not None:
            if not isinstance(examples, list):
                return "message_rules.style_examples must be an array"
            for idx, item in enumerate(examples):
                if not isinstance(item, dict):
                    return f"message_rules.style_examples[{idx}] must be an object"
                reply = item.get("reply")
                if not isinstance(reply, str) or not reply.strip():
                    return (
                        f"message_rules.style_examples[{idx}].reply must be a "
                        "non-empty string"
                    )
                for opt_key in ("label", "context", "incoming"):
                    val = item.get(opt_key)
                    if val is not None and not isinstance(val, str):
                        return (
                            f"message_rules.style_examples[{idx}].{opt_key} "
                            "must be a string when set"
                        )

    end_goals = config.get("conversation_end_goals")
    if isinstance(end_goals, dict):
        for bucket in ("preferred", "fallback"):
            items = end_goals.get(bucket)
            if items is None:
                continue
            if not isinstance(items, list):
                return f"conversation_end_goals.{bucket} must be an array"
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    return f"conversation_end_goals.{bucket}[{idx}] must be an object"
                if not item.get("id"):
                    return f"conversation_end_goals.{bucket}[{idx}].id is required"

    router = config.get("router")
    if isinstance(router, dict):
        timeout = router.get("step_timeout_hours")
        if timeout is not None and (not isinstance(timeout, int) or timeout <= 0):
            return "router.step_timeout_hours must be a positive integer"
        priorities = router.get("step4_path_priority")
        if priorities is not None:
            if not isinstance(priorities, list) or not all(
                isinstance(item, str) and item.strip() for item in priorities
            ):
                return (
                    "router.step4_path_priority must be an array of non-empty strings"
                )
        routes = router.get("signal_routes")
        if routes is not None and not isinstance(routes, dict):
            return "router.signal_routes must be an object"

    return None
