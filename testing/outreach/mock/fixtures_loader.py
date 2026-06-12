"""
Load mock regression scenarios from ``outreach/mock/fixtures/*.json``.

Each fixture file is the single source of truth for:

- Mock DM scripting (``prospect``, ``replies``, ``connection_accepted``, ``end_condition``)
- Regression transition specs (``rounds`` with ``allowed_actions`` / ``allowed_stages``)
- Case metadata surfaced in the dashboard regression panel

Consumed by ``tools/mock.py``, ``outreach/regression_harness.py``, and ``web/mock_conversation.py``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _read_fixture(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid mock fixture {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"mock fixture must be a JSON object: {path}")
    case_id = raw.get("case_id") or path.stem
    raw.setdefault("case_id", case_id)
    return raw


@lru_cache(maxsize=1)
def load_all_fixtures() -> dict[str, dict[str, Any]]:
    """Return every ``*.json`` file under ``fixtures/``, keyed by ``case_id``."""
    if not FIXTURES_DIR.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        blob = _read_fixture(path)
        out[str(blob["case_id"])] = blob
    return out


def list_case_ids() -> list[str]:
    return sorted(load_all_fixtures())


def get_fixture(case_id: str) -> dict[str, Any] | None:
    return load_all_fixtures().get(case_id)


def load_test_cases() -> dict[str, dict[str, Any]]:
    """Shape expected by ``tools/mock.py`` (mock session scripting only)."""
    out: dict[str, dict[str, Any]] = {}
    for case_id, blob in load_all_fixtures().items():
        out[case_id] = {
            "description": blob.get("description"),
            "prospect": blob.get("prospect") or {},
            "connection_accepted": bool(blob.get("connection_accepted", False)),
            "end_condition": blob.get("end_condition"),
            "replies": list(blob.get("replies") or []),
        }
    return out


def load_regression_specs() -> dict[str, dict[str, Any]]:
    """Shape expected by ``outreach/regression_harness.py`` transition checks."""
    out: dict[str, dict[str, Any]] = {}
    for case_id, blob in load_all_fixtures().items():
        rounds_raw = blob.get("rounds") or []
        rounds: list[dict[str, Any]] = []
        for row in rounds_raw:
            if not isinstance(row, dict):
                continue
            spec: dict[str, Any] = {
                "id": row.get("id"),
                "allowed_actions": frozenset(row.get("allowed_actions") or []),
            }
            if row.get("allowed_stages") is not None:
                spec["allowed_stages"] = frozenset(row.get("allowed_stages") or [])
            if row.get("assert_meeting"):
                spec["assert_meeting"] = True
            rounds.append(spec)
        out[case_id] = {
            "rounds": rounds,
            "repeat_final": bool(blob.get("repeat_final", False)),
            "terminal": dict(blob.get("terminal") or {}),
            "profile_url": blob.get("profile_url"),
            "prospect_id": blob.get("prospect_id"),
        }
    return out


def list_case_summaries() -> list[dict[str, Any]]:
    """Dashboard-friendly metadata for the regression case picker."""
    summaries: list[dict[str, Any]] = []
    for case_id, blob in load_all_fixtures().items():
        replies = blob.get("replies") or []
        prospect = blob.get("prospect") or {}
        summaries.append(
            {
                "case_id": case_id,
                "description": blob.get("description"),
                "end_condition": blob.get("end_condition"),
                "connection_accepted": blob.get("connection_accepted"),
                "total_reply_slots": len(replies),
                "non_null_replies": sum(
                    1 for r in replies if isinstance(r, dict) and r.get("text")
                ),
                "prospect_name": prospect.get("name"),
                "profile_url": blob.get("profile_url"),
                "prospect_id": blob.get("prospect_id"),
            }
        )
    summaries.sort(key=lambda r: str(r.get("case_id")))
    return summaries


def reload_fixtures() -> None:
    """Clear cached fixtures (tests only)."""
    load_all_fixtures.cache_clear()
