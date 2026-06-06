"""
Read-only view onto the mock LinkedIn DM session(s) for the dashboard.

The mock backend in ``tools/mock.py`` persists every send/reply turn to
``outreach/mock/mock_linkedin_sessions.json`` (atomic write). The dashboard's
mock view polls this module so the UI can animate new messages as they land
during a regression run.

Pairs each session with the matching ``conversations/<id>.json`` so the panel
shows planner-side state (next_action, planned_message, outreach_stage) next
to the raw thread.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from web.dashboard_data import _read_json, mock_base

REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = REPO_ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

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


def _import_mock_module() -> Any | None:
    """Lazily load ``tools/mock.py`` (matches ``outreach/regression_harness``)."""
    try:
        import mock as _mock  # type: ignore[import-not-found]

        return _mock
    except (ImportError, ModuleNotFoundError):
        return None


def _load_test_case_meta(case_id: str | None) -> dict[str, Any] | None:
    """Pull description / end_condition / total replies from ``tools/mock.py``."""
    if not case_id:
        return None
    mod = _import_mock_module()
    if mod is None or not hasattr(mod, "TEST_CASES"):
        return None
    tc = mod.TEST_CASES.get(case_id)
    if not isinstance(tc, dict):
        return None
    replies = tc.get("replies") or []
    return {
        "description": tc.get("description"),
        "end_condition": tc.get("end_condition"),
        "connection_accepted": tc.get("connection_accepted"),
        "total_reply_slots": len(replies),
        "non_null_replies": sum(1 for r in replies if r is not None),
        "prospect_name": (tc.get("prospect") or {}).get("name"),
    }


def list_test_cases() -> dict[str, Any]:
    """Surface ``TEST_CASES`` for the regression panel's case picker."""
    mod = _import_mock_module()
    if mod is None or not hasattr(mod, "TEST_CASES"):
        return {"cases": []}
    out: list[dict[str, Any]] = []
    for cid, tc in mod.TEST_CASES.items():
        replies = tc.get("replies") or []
        out.append(
            {
                "case_id": cid,
                "description": tc.get("description"),
                "end_condition": tc.get("end_condition"),
                "connection_accepted": tc.get("connection_accepted"),
                "total_reply_slots": len(replies),
                "non_null_replies": sum(1 for r in replies if r is not None),
                "prospect_name": (tc.get("prospect") or {}).get("name"),
            }
        )
    out.sort(key=lambda r: str(r.get("case_id")))
    return {"cases": out}


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


def _shape_session(blob: dict[str, Any]) -> dict[str, Any]:
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

    return {
        "profile_url": profile_url,
        "prospect_id": pid,
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
        "conversation": conversation,
    }


def get_mock_conversations() -> dict[str, Any]:
    """Return every persisted mock session along with its conversation snapshot."""
    base = mock_base()
    raw = _read_json(base / SESSION_FILE, {"sessions": {}})
    sessions = raw.get("sessions") if isinstance(raw, dict) else {}
    if not isinstance(sessions, dict):
        sessions = {}
    items: list[dict[str, Any]] = []
    for key, blob in sessions.items():
        if not isinstance(blob, dict):
            continue
        shaped = _shape_session(blob)
        shaped["session_key"] = key
        items.append(shaped)
    items.sort(key=lambda s: s.get("loaded_at") or "", reverse=True)
    return {
        "data_root": str(base),
        "store_path": str(base / SESSION_FILE),
        "total": len(items),
        "sessions": items,
    }
