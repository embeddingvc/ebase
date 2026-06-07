"""
Read-only view onto the mock LinkedIn DM session(s) for the dashboard.

The mock backend in ``tools/mock.py`` persists every send/reply turn to
``outreach/mock/mock_linkedin_sessions.json`` (atomic write). The dashboard's
mock view polls this module so the UI can animate new messages as they land
during a regression run.

Every fixture under ``outreach/mock/fixtures/*.json`` is always listed — even
before a regression run creates a live session — so the operator can browse
scripted replies and expected stages for all test cases.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from outreach.mock.fixtures_loader import get_fixture, list_case_summaries
from web.dashboard_data import _read_json, mock_base

SESSION_FILE = "mock_linkedin_sessions.json"


def _derive_prospect_id(profile_url: str | None) -> str | None:
    """Same slug rule the mock backend uses (``/in/<slug>`` → ``snake_case``)."""
    if not profile_url:
        return None
    try:
        path = urlparse(profile_url.strip()).path
    except (ValueError, TypeError):
        return None
    m = re.search(r"/in/([^/?#]+)", path, re.I)
    if not m:
        return None
    slug = m.group(1).strip().lower().replace("-", "_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug or None


def _normalise_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/").lower()


def _load_test_case_meta(case_id: str | None) -> dict[str, Any] | None:
    """Pull description / end_condition / total replies from fixture JSON."""
    if not case_id:
        return None
    blob = get_fixture(case_id)
    if not blob:
        return None
    replies = blob.get("replies") or []
    prospect = blob.get("prospect") or {}
    rounds = blob.get("rounds") or []
    return {
        "description": blob.get("description"),
        "end_condition": blob.get("end_condition"),
        "connection_accepted": blob.get("connection_accepted"),
        "total_reply_slots": len(replies),
        "non_null_replies": sum(
            1 for r in replies if isinstance(r, dict) and r.get("text")
        ),
        "prospect_name": prospect.get("name"),
        "rounds_count": len(rounds),
    }


def list_test_cases() -> dict[str, Any]:
    """Surface mock fixtures for the regression panel's case picker."""
    return {"cases": list_case_summaries()}


def _shape_scripted_replies(replies: list[Any]) -> list[dict[str, Any]]:
    """Prospect reply slots from the fixture (preview before a live run)."""
    out: list[dict[str, Any]] = []
    for idx, reply in enumerate(replies or []):
        if not isinstance(reply, dict) or not reply.get("text"):
            continue
        out.append(
            {
                "index": idx,
                "sender": "prospect",
                "text": str(reply.get("text") or ""),
                "attachments": list(reply.get("attachments") or []),
                "sequence_step": None,
                "scripted_slot": idx,
            }
        )
    return out


def _shape_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise raw mock history rows into the UI's chat-bubble schema."""
    out: list[dict[str, Any]] = []
    op_step = 0
    for idx, entry in enumerate(history or []):
        if not isinstance(entry, dict):
            continue
        is_self = bool(entry.get("self"))
        sender = "operator" if is_self else "prospect"
        if is_self:
            op_step += 1
        out.append(
            {
                "index": idx,
                "sender": sender,
                "text": str(entry.get("message") or ""),
                "attachments": list(entry.get("attachments") or []),
                "sequence_step": op_step if is_self else None,
            }
        )
    return out


def _shape_session(blob: dict[str, Any], *, live: bool = True) -> dict[str, Any]:
    """Build one session payload; pulls planner state from the conv JSON."""
    profile_url = blob.get("profile_url") or ""
    case_id = blob.get("test_case_id")
    history = _shape_history(blob.get("history") or [])
    pid = _derive_prospect_id(profile_url)

    conversation: dict[str, Any] | None = None
    prospect: dict[str, Any] | None = None
    if pid:
        base = mock_base()
        conv_blob = _read_json(base / "conversations" / f"{pid}.json", None)
        if isinstance(conv_blob, dict):
            conversation = {
                "outreach_stage": conv_blob.get("outreach_stage"),
                "last_action": conv_blob.get("last_action"),
                "last_action_timestamp": conv_blob.get("last_action_timestamp"),
                "next_action": conv_blob.get("next_action"),
                "next_action_after": conv_blob.get("next_action_after"),
                "planned_message": conv_blob.get("planned_message"),
                "email": conv_blob.get("email"),
                "meeting_link": conv_blob.get("meeting_link"),
                "ended_at": conv_blob.get("ended_at"),
                "ended_reason": conv_blob.get("ended_reason"),
                "sequence_step": conv_blob.get("sequence_step"),
                "stage_history": conv_blob.get("stage_history") or [],
                "messages_persisted": len(conv_blob.get("messages") or []),
            }
        prospect_blob = _read_json(base / "prospects" / f"{pid}.json", None)
        if isinstance(prospect_blob, dict):
            prospect = {
                "name": prospect_blob.get("name"),
                "title": prospect_blob.get("title"),
                "company": prospect_blob.get("company"),
                "connection_status": prospect_blob.get("connection_status"),
                "outreach_stage": prospect_blob.get("outreach_stage"),
            }

    fixture = get_fixture(case_id) if case_id else None
    if prospect is None and isinstance(fixture, dict):
        fp = fixture.get("prospect") or {}
        prospect = {
            "name": fp.get("name"),
            "title": fp.get("title"),
            "company": fp.get("company"),
        }

    return {
        "profile_url": profile_url,
        "prospect_id": pid or (fixture or {}).get("prospect_id"),
        "prospect": prospect,
        "test_case_id": case_id,
        "test_case": _load_test_case_meta(case_id),
        "connection_accepted": bool(blob.get("connection_accepted", False)),
        "ended": bool(blob.get("ended", False)),
        "ended_reason": blob.get("ended_reason"),
        "loaded_at": blob.get("loaded_at"),
        "messages_sent": int(blob.get("messages_sent") or 0),
        "history": history,
        "history_length": len(history),
        "scripted_replies": _shape_scripted_replies(
            (fixture or {}).get("replies") or []
        ),
        "live": live,
        "conversation": conversation,
    }


def _fixture_placeholder(blob: dict[str, Any]) -> dict[str, Any]:
    """Dashboard row for a fixture with no persisted mock session yet."""
    case_id = str(blob.get("case_id") or "")
    profile_url = str(blob.get("profile_url") or "")
    prospect = blob.get("prospect") or {}
    return {
        "session_key": f"fixture:{case_id}",
        "profile_url": profile_url,
        "prospect_id": blob.get("prospect_id") or _derive_prospect_id(profile_url),
        "prospect": {
            "name": prospect.get("name"),
            "title": prospect.get("title"),
            "company": prospect.get("company"),
        },
        "test_case_id": case_id,
        "test_case": _load_test_case_meta(case_id),
        "connection_accepted": bool(blob.get("connection_accepted", False)),
        "ended": False,
        "ended_reason": None,
        "loaded_at": None,
        "messages_sent": 0,
        "history": [],
        "history_length": 0,
        "scripted_replies": _shape_scripted_replies(blob.get("replies") or []),
        "live": False,
        "conversation": None,
    }


def get_mock_conversations() -> dict[str, Any]:
    """Return all fixture cases merged with any live mock LinkedIn sessions."""
    base = mock_base()
    raw = _read_json(base / SESSION_FILE, {"sessions": {}})
    sessions = raw.get("sessions") if isinstance(raw, dict) else {}
    if not isinstance(sessions, dict):
        sessions = {}

    live_items: list[dict[str, Any]] = []
    live_by_case: dict[str, dict[str, Any]] = {}
    for key, blob in sessions.items():
        if not isinstance(blob, dict):
            continue
        shaped = _shape_session(blob, live=True)
        shaped["session_key"] = key
        live_items.append(shaped)
        cid = shaped.get("test_case_id")
        if cid:
            live_by_case[str(cid)] = shaped

    merged: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for summary in list_case_summaries():
        case_id = str(summary["case_id"])
        seen_cases.add(case_id)
        if case_id in live_by_case:
            merged.append(live_by_case[case_id])
            continue
        fixture = get_fixture(case_id)
        if fixture:
            merged.append(_fixture_placeholder(fixture))

    for item in live_items:
        cid = item.get("test_case_id")
        if cid and str(cid) in seen_cases:
            continue
        merged.append(item)

    merged.sort(
        key=lambda s: (
            0 if s.get("live") else 1,
            s.get("test_case_id") or "",
        )
    )

    cases = list_case_summaries()
    return {
        "data_root": str(base),
        "store_path": str(base / SESSION_FILE),
        "cases": cases,
        "total": len(merged),
        "live_total": sum(1 for s in merged if s.get("live")),
        "sessions": merged,
    }
