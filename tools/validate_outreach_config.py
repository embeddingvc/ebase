#!/usr/bin/env python3
"""
Validate outreach/config/persona.json and/or conversation_planner.json.

Lets a skill (ebase-setup, ebase-sync-persona) write these files directly
with Read/Write and then confirm the result is well-formed, without going
through the MCP server's config tools. Also used by install.sh's tone
questionnaire step.

Usage:
    uv run python tools/validate_outreach_config.py --persona outreach/config/persona.json
    uv run python tools/validate_outreach_config.py --planner outreach/config/conversation_planner.json
    uv run python tools/validate_outreach_config.py --persona ... --planner ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from outreach_config import validate_conversation_planner_config, validate_persona_config


def _validate_file(path: Path, validator: Callable[[dict], str | None]) -> str | None:
    if not path.is_file():
        return f"not found: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return f"cannot read {path}: {exc}"
    except json.JSONDecodeError as exc:
        return f"invalid JSON in {path}: {exc}"
    return validator(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", type=Path, help="Path to persona.json")
    parser.add_argument("--planner", type=Path, help="Path to conversation_planner.json")
    args = parser.parse_args()

    if not args.persona and not args.planner:
        parser.error("pass at least one of --persona / --planner")

    errors: list[str] = []

    if args.persona:
        err = _validate_file(args.persona, validate_persona_config)
        if err:
            errors.append(f"persona: {err}")
        else:
            print(f"ok: {args.persona}")

    if args.planner:
        err = _validate_file(args.planner, validate_conversation_planner_config)
        if err:
            errors.append(f"planner: {err}")
        else:
            print(f"ok: {args.planner}")

    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
