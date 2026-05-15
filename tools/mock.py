"""
tools/mock.py — LinkedIn MCP mock backend.

All mock-mode logic lives here so server.py stays thin.  Nothing depends on
MCP.  :func:`handle_parse_profile` imports small slot-formatting helpers from
``outreach.browser`` so mock output matches the live ``parse_profile`` schema;
other handlers stay free of Playwright.

LinkedIn tool mocks (``scrape_profile``, ``is_first_degree_connection``, ``send_connection_request``,
``send_message``, ``fetch_chat_history``) always centre on the ``_ALEX_CHEN`` fixture: if
``handle_load_test_case`` was not used first (tests only), a session is auto-created from ``happy_path``,
which uses that prospect and its scripted replies. Other scenarios require ``handle_load_test_case`` first.

Public surface
──────────────
  Data / state
    TEST_CASES       dict of built-in test scenarios
    MockSession      dataclass representing one simulated conversation
    sessions         dict[str, MockSession], keyed by normalised profile URL

  Helpers
    normalise_url(url)                   → str
    get_session(profile_url)             → MockSession | None

  Async handlers (called by server.py when in mock mode; test-only helpers are not MCP tools)
    handle_list_test_cases()             → str   (tests / inspection only)
    handle_load_test_case(id, url)       → str   (tests / inspection only)
    handle_get_mock_state(url)           → str   (tests / inspection only)
    handle_scrape_profile(url)           → str
    handle_parse_profile(url)          → str
    handle_is_first_degree_connection(url) → str
    handle_send_connection_request(url, note) → str
    handle_send_message(url, message)    → str
    handle_fetch_chat_history(url)       → str
    handle_create_new_post(content)      → str
    handle_reply_to_post(post_url, comment) → str
    handle_browse_forever(reaction, cdp_url) → str
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("linkedin.mock")


# ═════════════════════════════════════════════════════════════════════════════
# PROSPECT FIXTURES
# ═════════════════════════════════════════════════════════════════════════════

# Default prospect used by all built-in test cases.
_ALEX_CHEN: dict[str, Any] = {
    "linkedin_url": "https://www.linkedin.com/in/alex-chen-softeng/",
    "name": "Alex Chen",
    "title": "Senior Software Engineer",
    "company": "Stripe",
    "location": "San Francisco, CA",
    "connection_degree": 2,
    "mutual_connections": ["Jordan Park", "Sam Liu"],
    "about": (
        "Distributed systems engineer with 6 years at Google and Stripe. "
        "Passionate about high-scale infrastructure, event-driven architectures, "
        "and developer tooling."
    ),
    "recent_posts": [
        {
            "text": (
                "Just wrapped up migrating our payment service to a new event-driven "
                "architecture. The latency improvements were worth every painful debugging "
                "session. Distributed systems are hard but beautiful."
            ),
            "likes": 142,
            "timestamp": "2026-03-20",
        },
        {
            "text": (
                "Hot take: the best engineers I've worked with all have a habit of "
                "writing things down. Docs, ADRs, post-mortems — it compounds over time."
            ),
            "likes": 89,
            "timestamp": "2026-03-15",
        },
    ],
    "connection_status": "none",
    "outreach_stage": "cold",
    "end_goal": "schedule_meeting",
    "outreach_topic": "Series A ML infra roles in the portfolio",
    "target_action": None,
    "notes": (
        "Strong distributed systems background. "
        "Mentioned open to new roles in a comment 3 weeks ago."
    ),
    "scraped_at": "2026-03-24T00:00:00Z",
}

# Default mock persona for all LinkedIn tools when ``handle_load_test_case`` was not called first.
# ``happy_path`` uses ``_ALEX_CHEN`` as its prospect and scripted replies.
_DEFAULT_MOCK_TEST_CASE_ID = "happy_path"



# ═════════════════════════════════════════════════════════════════════════════
# TEST CASE REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

# Schema for each test case:
#
#   description         str   — human-readable summary
#   prospect            dict  — returned verbatim by scrape_profile
#   connection_accepted bool  — whether the prospect accepts the connection
#   end_condition       str   — expected final outcome label
#   replies             list  — scripted prospect replies, indexed by operator
#                               message number (0-based):
#                                 index 0 = reply to the connection note
#                                 index 1 = reply to the 1st send_message call
#                                 index 2 = reply to the 2nd send_message call
#                                 …
#                               Each non-None entry: {"text": str, "attachments": list}
#                               None means the prospect stays silent at that turn.

TEST_CASES: dict[str, dict[str, Any]] = {

    # ── 1. Full happy path ────────────────────────────────────────────────────
    "happy_path": {
        "description": (
            "Full 4-turn conversation. Prospect is curious about career options, "
            "discusses early-stage ML infra ambitions, and ultimately shares resume."
        ),
        "prospect": _ALEX_CHEN,
        "connection_accepted": True,
        "end_condition": "meeting_scheduled",
        "replies": [
            # [0] reply to connection note
            {
                "text": (
                    "Thanks Nova! Yeah I'm always curious what's out there. "
                    "What kind of companies are you working with?"
                ),
            },
            # [1] reply to first DM (career question)
            {
                "text": (
                    "Honestly I love the scale problems at Stripe but I've been itching "
                    "to work on something earlier stage. The architecture migration was fun "
                    "but I miss the 0-to-1 feeling. Been looking at some ML infra teams."
                ),
            },
            # [2] reply to second DM (join vs build)
            {
                "text": (
                    "Joining for now — I want to learn the ML side more before starting "
                    "something. Ideally a Series A company where I can own a big chunk of "
                    "the infra. Definitely open to hearing about what's in your network."
                ),
            },
            # [3] reply to third DM (resume request)
            {
                "text": "Hey I would love to meet sometime for a more thorough conversation. I'm available anytime next week.",
            },
        ],
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MockSession:
    """
    Simulated conversation state for one profile URL.

    history
        Accumulated DM thread in the same format fetch_chat_history returns:
        [{"message": str, "self": bool}, …]
        "self": True  = operator (us)
        "self": False = prospect

    messages_sent
        Count of operator bubbles in ``history`` after each tool call (synced for
        mock state previews).  The connection note counts as one operator message.
    """
    test_case_id: str
    profile_url: str
    connection_accepted: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)
    messages_sent: int = 0
    ended: bool = False
    ended_reason: str | None = None
    loaded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Keyed by normalised profile URL (lowercase, no trailing slash).
sessions: dict[str, MockSession] = {}


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def normalise_url(url: str) -> str:
    """
    Canonical session key for one LinkedIn profile so www / non-www and trailing
    slashes do not split state across two sessions.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    scheme = (p.scheme or "https").lower()
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "").rstrip("/").lower()
    return f"{scheme}://{host}{path}"


def get_session(profile_url: str) -> MockSession | None:
    """Return the active MockSession for profile_url, or None."""
    return sessions.get(normalise_url(profile_url))


def ensure_default_mock_session(profile_url: str) -> MockSession:
    """
    Return the session for profile_url, creating one from ``_DEFAULT_MOCK_TEST_CASE_ID``
    (``happy_path`` → _ALEX_CHEN) if ``handle_load_test_case`` was never called.
    """
    key = normalise_url(profile_url)
    existing = sessions.get(key)
    if existing is not None:
        return existing
    tc = TEST_CASES[_DEFAULT_MOCK_TEST_CASE_ID]
    sessions[key] = MockSession(
        test_case_id=_DEFAULT_MOCK_TEST_CASE_ID,
        profile_url=profile_url,
        connection_accepted=tc["connection_accepted"],
    )
    logger.info(
        "mock: auto-initialized session  test_case=%s  profile=%s",
        _DEFAULT_MOCK_TEST_CASE_ID,
        profile_url,
    )
    return sessions[key]


def _append_prospect_reply(session: MockSession, reply_index: int) -> None:
    """
    Look up replies[reply_index] for the session's test case and, if it is a
    non-None dict, append the prospect's message to session.history.
    """
    tc = TEST_CASES[session.test_case_id]
    replies = tc.get("replies", [])

    if reply_index >= len(replies):
        logger.debug(
            "mock: no reply defined at index %d (prospect silent)", reply_index
        )
        return  # Beyond script end — prospect stays silent.

    reply = replies[reply_index]
    if reply is None:
        logger.debug(
            "mock: reply[%d] is None (explicitly scripted silence)", reply_index
        )
        return

    entry: dict[str, Any] = {"message": reply["text"], "self": False}
    if reply.get("attachments"):
        entry["attachments"] = reply["attachments"]
    session.history.append(entry)
    logger.info(
        "mock: prospect reply appended  index=%d  chars=%d  attachments=%d",
        reply_index,
        len(reply["text"]),
        len(reply.get("attachments", [])),
    )


# ═════════════════════════════════════════════════════════════════════════════
# MANAGEMENT HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

async def handle_list_test_cases() -> str:
    """Return a JSON summary of all built-in test cases."""
    result = []
    for tc_id, tc in TEST_CASES.items():
        replies = tc.get("replies", [])
        non_null = sum(1 for r in replies if r is not None)
        result.append({
            "test_case_id": tc_id,
            "description": tc["description"],
            "connection_accepted": tc["connection_accepted"],
            "end_condition": tc["end_condition"],
            "total_reply_slots": len(replies),
            "non_null_replies": non_null,
            "prospect_name": tc["prospect"].get("name"),
        })
    return json.dumps(result, indent=2, ensure_ascii=False)


async def handle_load_test_case(test_case_id: str, profile_url: str) -> str:
    """
    Create (or reset) a MockSession for profile_url using the named test case.
    Returns a human-readable confirmation string.
    """
    if test_case_id not in TEST_CASES:
        available = ", ".join(sorted(TEST_CASES))
        return (
            f"Unknown test case '{test_case_id}'.\n"
            f"Available: {available}\n"
            "Use await handle_list_test_cases() for full details."
        )

    tc = TEST_CASES[test_case_id]
    key = normalise_url(profile_url)
    sessions[key] = MockSession(
        test_case_id=test_case_id,
        profile_url=profile_url,
        connection_accepted=tc["connection_accepted"],
    )
    logger.info("handle_load_test_case  test_case=%s  profile=%s", test_case_id, profile_url)

    replies = tc.get("replies", [])
    total = len(replies)
    non_null = sum(1 for r in replies if r is not None)
    prospect_name = tc["prospect"].get("name", "Unknown")

    return (
        f"✓ Test case '{test_case_id}' loaded for {profile_url}\n\n"
        f"  Description  : {tc['description']}\n"
        f"  Prospect     : {prospect_name}\n"
        f"  Connection   : {'accepted' if tc['connection_accepted'] else 'never accepted (ghosted)'}\n"
        f"  End condition: {tc['end_condition']}\n"
        f"  Reply slots  : {total} total ({non_null} non-null, {total - non_null} silent)\n\n"
        "Next step: call send_connection_request(profile_url, note)."
    )


async def handle_get_mock_state(profile_url: str) -> str:
    """Return a JSON snapshot of the current session state for profile_url."""
    session = get_session(profile_url)
    if session is None:
        return json.dumps(
            {
                "error": (
                    f"No mock session found for {profile_url!r}. "
                    "Call await handle_load_test_case(...) first."
                )
            },
            indent=2,
        )

    tc = TEST_CASES[session.test_case_id]
    replies = tc.get("replies", [])
    remaining_slots = len(replies) - session.messages_sent
    remaining_non_null = sum(
        1 for r in replies[session.messages_sent:] if r is not None
    )

    history_preview = [
        {
            "index": i,
            "sender": "operator" if entry["self"] else "prospect",
            "preview": (
                entry["message"][:80] + ("…" if len(entry["message"]) > 80 else "")
            ),
            "has_attachments": bool(entry.get("attachments")),
        }
        for i, entry in enumerate(session.history)
    ]

    state = {
        "profile_url": session.profile_url,
        "test_case_id": session.test_case_id,
        "description": tc["description"],
        "end_condition": tc["end_condition"],
        "connection_accepted": session.connection_accepted,
        "messages_sent": session.messages_sent,
        "history_length": len(session.history),
        "remaining_reply_slots": max(0, remaining_slots),
        "remaining_non_null_replies": remaining_non_null,
        "ended": session.ended,
        "ended_reason": session.ended_reason,
        "loaded_at": session.loaded_at,
        "history_preview": history_preview,
    }
    return json.dumps(state, indent=2, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════════════════
# TOOL HANDLERS
# ═════════════════════════════════════════════════════════════════════════════

async def handle_scrape_profile(profile_url: str) -> str:
    """
    Return the prospect dict for the active or auto-created mock session
    (always the ``_ALEX_CHEN``-based prospect from the session's test case).
    """
    session = ensure_default_mock_session(profile_url)
    tc = TEST_CASES[session.test_case_id]
    profile = dict(tc["prospect"])
    profile["linkedin_url"] = profile_url
    profile["scraped_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "scrape_profile MOCK (test case: %s)  url=%s",
        session.test_case_id,
        profile_url,
    )
    return json.dumps(profile, ensure_ascii=False, indent=2)


async def handle_parse_profile(profile_url: str) -> str:
    """
    Return a ``parse_profile`` v2 document (structured fields only; no raw page dump).

    Uses the active test-case prospect plus deterministic multi-line blobs so the
    same slot-filling helpers as live mode shape ``experience`` / ``education`` rows.
    """
    from outreach.browser import (
        _pp_degree_label,
        _pp_structure_activity_update,
        _pp_structure_education_card,
        _pp_structure_experience_card,
        _pp_structure_recommendation_card,
        _pp_structure_skill_row,
        _pp_word_count,
    )

    session = ensure_default_mock_session(profile_url)
    tc = TEST_CASES[session.test_case_id]
    prospect = dict(tc["prospect"])
    url = profile_url.strip()
    mutual_names = list(prospect.get("mutual_connections") or [])
    name = prospect.get("name") or "Member"
    headline = prospect.get("title") or ""
    location = prospect.get("location") or ""
    degree = prospect.get("connection_degree")
    about = (prospect.get("about") or "").strip()
    posts_raw = list(prospect.get("recent_posts") or [])

    slug = ""
    m = re.search(r"/in/([^/?#]+)", url, flags=re.I)
    if m:
        slug = m.group(1).strip("/")

    exp_blob = (
        f"{headline or 'Senior Software Engineer'}\n"
        f"{prospect.get('company') or 'Example Corp'} · Full-time\n"
        f"Jan 2020 – Present · 5 yrs\n"
        f"{location or 'San Francisco Bay Area'}\n"
        f"Focus: high-scale backend and reliability."
    )
    edu_blob = (
        "Stanford University\n"
        "BS · Computer Science\n"
        "2014 – 2018\n"
        "Activities: ACM chapter."
    )
    experience = [_pp_structure_experience_card(exp_blob)]
    education = [_pp_structure_education_card(edu_blob)]
    skills = [
        _pp_structure_skill_row("Python\n· 99+ endorsements"),
        _pp_structure_skill_row("Distributed Systems"),
    ]
    rec_blob = (
        "Jordan Park\n"
        "Managed Alex directly at Stripe\n"
        f"{name} is one of the strongest infra engineers I've worked with — "
        "owns complex migrations end-to-end."
    )
    recommendations = [_pp_structure_recommendation_card(rec_blob)]

    mutual_objs = [{"display_name": n} for n in mutual_names]
    exp0 = experience[0] if experience else {}
    skills_preview = [s["name"] for s in skills[:15] if s.get("name")]

    subject: dict[str, Any] = {
        "identity": {
            "linkedin_url": url,
            "public_id": slug or None,
            "full_name": name,
            "headline": headline,
            "location": location,
            "network": {"degree": degree, "label": _pp_degree_label(degree)},
        },
        "narrative": {
            "about": about,
            "about_metrics": {
                "characters": len(about),
                "words": _pp_word_count(about),
            },
        },
        "career_signals": {
            "primary_role": exp0.get("role_title"),
            "primary_organization": exp0.get("organization"),
            "employment_type_primary": exp0.get("employment_type"),
            "tenure_primary": exp0.get("tenure"),
            "skills_preview": skills_preview,
        },
    }

    updates = [
        _pp_structure_activity_update(i, p if isinstance(p, dict) else {"text": str(p)})
        for i, p in enumerate(posts_raw)
    ]
    total_words = sum(u["metrics"]["words"] for u in updates)
    activity_url = url.rstrip("/") + "/recent-activity/all/"
    parsed_at = datetime.now(timezone.utc).isoformat()

    parsed: dict[str, Any] = {
        "subject": subject,
        "relations": {
            "experience": experience,
            "education": education,
            "skills": skills,
            "recommendations": recommendations,
            "mutual_connections": mutual_objs,
            "rollup": {
                "experience_count": len(experience),
                "education_count": len(education),
                "skills_count": len(skills),
                "recommendations_count": len(recommendations),
                "mutual_connections_count": len(mutual_objs),
                "low_confidence_experience": sum(
                    1 for e in experience if e.get("parse_confidence") == "none"
                ),
            },
        },
        "activity": {
            "feed_url": activity_url,
            "stats": {
                "updates_collected": len(updates),
                "total_words": total_words,
                "any_update_has_url": any(u["metrics"]["has_urls"] for u in updates),
                "updates_with_hashtags": sum(
                    1 for u in updates if u["metrics"]["hashtag_count"] > 0
                ),
            },
            "updates": updates,
        },
        "crawl_log": [
            {"phase": "main_profile", "status": "ok", "mock": True},
            {"phase": "mutual_connections", "status": "ok", "count": len(mutual_objs), "mock": True},
            {"phase": "experience", "status": "ok", "items": len(experience), "mock": True},
            {"phase": "education", "status": "ok", "items": len(education), "mock": True},
            {"phase": "skills", "status": "ok", "items": len(skills), "mock": True},
            {"phase": "recommendations", "status": "ok", "items": len(recommendations), "mock": True},
            {"phase": "activity_feed", "status": "ok", "posts": len(updates), "mock": True},
        ],
        "meta": {"parsed_at": parsed_at, "schema": "linkedin.parse_profile/v2", "mock": True},
    }
    logger.info(
        "parse_profile MOCK (test case: %s)  url=%s",
        session.test_case_id,
        profile_url,
    )
    return json.dumps(parsed, ensure_ascii=False, indent=2)


async def handle_is_first_degree_connection(profile_url: str) -> str:
    """
    Return whether the mock session is in a 1st-degree (DM-ready) state.
    """
    return json.dumps(
        {
            "first_degree": True,
            "profile_url": profile_url,
        },
        ensure_ascii=False,
        indent=2,
    )


async def handle_send_connection_request(profile_url: str, note: str) -> str:
    """
    Record the connection note as operator message 0 and append the first
    scripted prospect reply (replies[0]) if the test case accepts the connection.
    """
    session = ensure_default_mock_session(profile_url)

    if session.messages_sent > 0:
        return (
            "[MOCK] Connection request already sent for this session. "
            "Call await handle_load_test_case(...) with the same URL to reset."
        )

    logger.info(
        "send_connection_request MOCK (test case: %s)  url=%s  note_len=%d",
        session.test_case_id, profile_url, len(note),
    )

    if session.connection_accepted:
        _append_prospect_reply(session, reply_index=0)
        return "ok"

    # Connection not accepted — note was sent but prospect ignores it.
    session.messages_sent = 1
    return (
        "ok — connection request sent. "
        "[MOCK: test case has connection_accepted=False — "
        "prospect will not accept; history will remain empty.]"
    )


async def handle_send_message(profile_url: str, message: str) -> str:
    """
    Append the operator's DM to history, then append the next scripted
    prospect reply (if any).  Increments messages_sent.
    """
    session = ensure_default_mock_session(profile_url)

    if not session.connection_accepted:
        return (
            "[MOCK] Message could not be sent — "
            "the test case has connection_accepted=False. "
            "This prospect never accepted the connection request."
        )

    op_before = sum(1 for h in session.history if h.get("self"))
    reply_index = op_before + 1

    session.history.append({"message": message, "self": True})
    session.messages_sent = sum(1 for h in session.history if h.get("self"))
    _append_prospect_reply(session, reply_index=reply_index)

    logger.info(
        "send_message MOCK (test case: %s)  url=%s  reply_index=%d  history_len=%d",
        session.test_case_id,
        profile_url,
        reply_index,
        len(session.history),
    )
    return "ok"


async def handle_fetch_chat_history(profile_url: str) -> str:
    """Return the current DM history for profile_url (Alex Chen session if not loaded yet)."""
    session = ensure_default_mock_session(profile_url)

    logger.info(
        "fetch_chat_history MOCK (test case: %s)  url=%s  history_len=%d",
        session.test_case_id, profile_url, len(session.history),
    )
    return json.dumps(session.history, ensure_ascii=False, indent=2)


async def handle_create_new_post(content: str) -> str:
    """Validate and acknowledge a post publication in mock mode."""
    text = (content or "").strip()
    if not text:
        return "Post content cannot be empty."
    if len(text) > 10_000:
        return "Post content too long (keep under ~10 000 chars)."
    logger.info("create_new_post MOCK  content_len=%d", len(text))
    return "[MOCK] ok"


async def handle_reply_to_post(post_url: str, comment: str) -> str:
    """Acknowledge a post comment in mock mode."""
    logger.info("reply_to_post MOCK  url=%s", post_url)
    return "[MOCK] ok"


async def handle_browse_forever(reaction: str, cdp_url: str) -> str:
    """Acknowledge a browse_forever request in mock mode (no background task)."""
    logger.info(
        "browse_forever MOCK (no browser)  cdp=%s  reaction=%s", cdp_url, reaction
    )
    return (
        "[MOCK] browse_forever — no background session started. "
        f"reaction={reaction!r}, cdp={cdp_url}."
    )
