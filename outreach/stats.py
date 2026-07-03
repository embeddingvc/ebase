"""
Outreach funnel/reply-rate aggregation for the ``get_outreach_stats`` MCP tool
and the ``/stats`` skill.

Reads connections.json, conversations/*.json, and prospects/*.json under the
active outreach data root (see outreach.data_paths) and rolls them up into a
single report. Aggregation lives here in Python rather than the skill layer
so it costs one MCP round trip instead of fetching every conversation file
one by one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from outreach.data_paths import _read_json, outreach_base

_SEQUENCE_STEPS = (1, 2, 3, 4, 5)
_CONVERTED_ENDED_REASONS = frozenset({"resume_received", "call_scheduled"})
_ACCEPTED_STATUSES = frozenset({"connected", "ended"})


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _load_connections() -> list[dict[str, Any]]:
    data = _read_json(outreach_base() / "connections.json", {"connections": []})
    return list(data.get("connections") or [])


def _load_conversations() -> list[dict[str, Any]]:
    conv_dir = outreach_base() / "conversations"
    if not conv_dir.is_dir():
        return []
    rows = []
    for path in sorted(conv_dir.glob("*.json")):
        row = _read_json(path, None)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _load_prospects() -> dict[str, dict[str, Any]]:
    prospects_dir = outreach_base() / "prospects"
    if not prospects_dir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(prospects_dir.glob("*.json")):
        row = _read_json(path, None)
        if isinstance(row, dict) and row.get("id"):
            out[row["id"]] = row
    return out


def _since_ok(ts: str | None, since: str | None) -> bool:
    # ISO 8601 timestamps sort lexically, so a "YYYY-MM-DD" cutoff compares
    # correctly against a full "YYYY-MM-DDTHH:MM:SS+00:00" value with no
    # date parsing needed.
    return since is None or (ts or "") >= since


def _is_converted(conv: dict[str, Any]) -> bool:
    return (
        conv.get("outreach_stage") == "converted"
        or conv.get("ended_reason") in _CONVERTED_ENDED_REASONS
    )


def _has_reply(conv: dict[str, Any]) -> bool:
    return any(m.get("sender") == "prospect" for m in conv.get("messages") or [])


def build_outreach_stats(since: str | None = None) -> dict[str, Any]:
    """Aggregate connections/conversations/prospects into a funnel report.

    ``since`` (optional, ``YYYY-MM-DD``) keeps only connections whose
    ``connected_at`` and conversations whose ``last_action_timestamp`` fall
    on or after that date.
    """
    connections = [c for c in _load_connections() if _since_ok(c.get("connected_at"), since)]
    conversations = [
        c for c in _load_conversations() if _since_ok(c.get("last_action_timestamp"), since)
    ]
    prospects = _load_prospects()

    by_stage: dict[str, int] = {}
    for conv in conversations:
        stage = conv.get("outreach_stage") or "cold"
        by_stage[stage] = by_stage.get(stage, 0) + 1

    sent = len(connections)
    accepted = sum(1 for c in connections if c.get("connection_status") in _ACCEPTED_STATUSES)
    pending = sum(1 for c in connections if c.get("connection_status") == "pending")
    ended = sum(1 for c in connections if c.get("connection_status") == "ended")

    replied = [c for c in conversations if _has_reply(c)]
    converted = [c for c in conversations if _is_converted(c)]

    by_ended_reason: dict[str, int] = {}
    for conv in conversations:
        reason = conv.get("ended_reason")
        if reason:
            by_ended_reason[reason] = by_ended_reason.get(reason, 0) + 1

    by_step: dict[str, dict[str, Any]] = {}
    for step in _SEQUENCE_STEPS:
        step_sent = step_replied = 0
        for conv in conversations:
            messages = conv.get("messages") or []
            for idx, msg in enumerate(messages):
                if msg.get("sender") == "operator" and msg.get("sequence_step") == step:
                    step_sent += 1
                    if any(m.get("sender") == "prospect" for m in messages[idx + 1 :]):
                        step_replied += 1
                    break
        if step_sent:
            by_step[str(step)] = {
                "sent": step_sent,
                "got_reply": step_replied,
                "reply_rate_pct": _pct(step_replied, step_sent),
            }

    by_end_goal: dict[str, dict[str, Any]] = {}
    conv_by_id = {c["prospect_id"]: c for c in conversations if c.get("prospect_id")}
    for pid in set(conv_by_id) | set(prospects):
        conv = conv_by_id.get(pid)
        prospect = prospects.get(pid)
        goal = (conv or {}).get("end_goal") or (prospect or {}).get("end_goal") or "none"
        entry = by_end_goal.setdefault(goal, {"total": 0, "converted": 0})
        entry["total"] += 1
        if conv and _is_converted(conv):
            entry["converted"] += 1
    for entry in by_end_goal.values():
        entry["rate_pct"] = _pct(entry["converted"], entry["total"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"total": len(conversations), "by_stage": by_stage},
        "connections": {
            "sent": sent,
            "accepted": accepted,
            "pending": pending,
            "ended": ended,
            "acceptance_rate_pct": _pct(accepted, sent),
        },
        "replies": {
            "total_replied": len(replied),
            "reply_rate_pct": _pct(len(replied), accepted),
        },
        "outcomes": {
            "total_converted": len(converted),
            "conversion_rate_pct": _pct(len(converted), accepted),
            "by_ended_reason": by_ended_reason,
        },
        "sequence": {"by_step": by_step},
        "by_end_goal": by_end_goal,
    }
