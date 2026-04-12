"""
tools/mock.py — LinkedIn MCP mock backend.

All mock-mode logic lives here so server.py stays thin.  Nothing in this
module depends on MCP or the browser layer; it is importable standalone and
fully testable without starting the server.

LinkedIn tool mocks (``scrape_profile``, ``send_connection_request``, ``send_message``,
``fetch_chat_history``) always centre on the ``_ALEX_CHEN`` fixture: if ``load_test_case``
was not called, a session is auto-created from ``happy_path``, which uses that prospect
and its scripted replies. Other scenarios still require ``load_test_case`` first.

Public surface
──────────────
  Data / state
    TEST_CASES       dict of built-in test scenarios
    MockSession      dataclass representing one simulated conversation
    sessions         dict[str, MockSession], keyed by normalised profile URL

  Helpers
    normalise_url(url)                   → str
    get_session(profile_url)             → MockSession | None

  Async handlers (one per MCP tool, called by server.py when in mock mode)
    handle_list_test_cases()             → str
    handle_load_test_case(id, url)       → str
    handle_get_mock_state(url)           → str
    handle_scrape_profile(url)           → str
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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
    "target_action": "request_resume",
    "notes": (
        "Strong distributed systems background. "
        "Mentioned open to new roles in a comment 3 weeks ago."
    ),
    "scraped_at": "2026-03-24T00:00:00Z",
}

# Default mock persona for all LinkedIn tools when ``load_test_case`` was not called first.
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
        "end_condition": "resume_shared",
        "replies": [
            # [0] reply to connection note
            {
                "text": (
                    "Thanks Nova! Yeah I'm always curious what's out there. "
                    "What kind of companies are you working with?"
                ),
                "attachments": [],
            },
            # [1] reply to first DM (career question)
            {
                "text": (
                    "Honestly I love the scale problems at Stripe but I've been itching "
                    "to work on something earlier stage. The architecture migration was fun "
                    "but I miss the 0-to-1 feeling. Been looking at some ML infra teams."
                ),
                "attachments": [],
            },
            # [2] reply to second DM (join vs build)
            {
                "text": (
                    "Joining for now — I want to learn the ML side more before starting "
                    "something. Ideally a Series A company where I can own a big chunk of "
                    "the infra. Definitely open to hearing about what's in your network."
                ),
                "attachments": [],
            },
            # [3] reply to third DM (resume request)
            {
                "text": "Sure, here you go!",
                "attachments": [
                    {
                        "type": "resume",
                        "url": "https://linkedin.com/dms/alex_chen_resume.pdf",
                        "filename": "alex_chen_resume.pdf",
                    }
                ],
            },
        ],
    },

    # ── 2. Not interested ─────────────────────────────────────────────────────
    "not_interested": {
        "description": (
            "Prospect politely declines right after the connection note. "
            "Planner should recognise the rejection and close the conversation."
        ),
        "prospect": _ALEX_CHEN,
        "connection_accepted": True,
        "end_condition": "not_interested",
        "replies": [
            # [0] reply to connection note
            {
                "text": (
                    "Hey Nova, thanks for reaching out but I'm not looking for anything "
                    "new right now. Happy at Stripe and plan to stay for a while. Best of luck!"
                ),
                "attachments": [],
            },
        ],
    },

    # ── 3. No reply / timeout ─────────────────────────────────────────────────
    "no_reply": {
        "description": (
            "Prospect replies once to show mild interest then goes silent. "
            "Planner should send a gentle follow-up then eventually time out."
        ),
        "prospect": _ALEX_CHEN,
        "connection_accepted": True,
        "end_condition": "timeout",
        "replies": [
            # [0] reply to connection note
            {
                "text": "Thanks Nova! Yeah I'm always curious what's out there.",
                "attachments": [],
            },
            None,   # [1] silent after first DM
            None,   # [2] silent after second DM — planner should give up
        ],
    },

    # ── 4. Ghosted — never accepted ───────────────────────────────────────────
    "ghosted_cold": {
        "description": (
            "Prospect never accepts the connection request. "
            "fetch_chat_history returns an empty thread; "
            "planner should eventually mark as timed-out."
        ),
        "prospect": _ALEX_CHEN,
        "connection_accepted": False,
        "end_condition": "timeout",
        "replies": [],
    },

    # ── 5. Eager referral — fast convert ─────────────────────────────────────
    "eager_referral": {
        "description": (
            "Prospect is actively job-seeking and converts after just one follow-up. "
            "Shares resume on turn 2 without much prompting."
        ),
        "prospect": _ALEX_CHEN,
        "connection_accepted": True,
        "end_condition": "resume_shared",
        "replies": [
            # [0] reply to connection note
            {
                "text": (
                    "Nova! Perfect timing — I've actually been actively looking. "
                    "I'd love to hear what you have. Can I send you my resume directly?"
                ),
                "attachments": [],
            },
            # [1] reply to first DM (invite to share)
            {
                "text": (
                    "Here's my resume. I'm particularly interested in ML infra or platform "
                    "engineering roles at Series A or B. Let me know what fits!"
                ),
                "attachments": [
                    {
                        "type": "resume",
                        "url": "https://linkedin.com/dms/alex_chen_resume_v2.pdf",
                        "filename": "alex_chen_resume_v2.pdf",
                    }
                ],
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
        Number of operator messages placed in history so far.
        Connection note = message 0; each send_message call increments this.
        Used as the index into TEST_CASES[id]["replies"] to decide which
        prospect reply (if any) to append after each operator turn.
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
    """Strip whitespace and trailing slash, then lowercase."""
    return url.strip().rstrip("/").lower()


def get_session(profile_url: str) -> MockSession | None:
    """Return the active MockSession for profile_url, or None."""
    return sessions.get(normalise_url(profile_url))


def ensure_default_mock_session(profile_url: str) -> MockSession:
    """
    Return the session for profile_url, creating one from ``_DEFAULT_MOCK_TEST_CASE_ID``
    (``happy_path`` → _ALEX_CHEN) if ``load_test_case`` was never called.
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
            "Call list_test_cases() for full details."
        )

    tc = TEST_CASES[test_case_id]
    key = normalise_url(profile_url)
    sessions[key] = MockSession(
        test_case_id=test_case_id,
        profile_url=profile_url,
        connection_accepted=tc["connection_accepted"],
    )
    logger.info("load_test_case  test_case=%s  profile=%s", test_case_id, profile_url)

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
                    "Call load_test_case first."
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


async def handle_send_connection_request(profile_url: str, note: str) -> str:
    """
    Record the connection note as operator message 0 and append the first
    scripted prospect reply (replies[0]) if the test case accepts the connection.
    """
    session = ensure_default_mock_session(profile_url)

    if session.messages_sent > 0:
        return (
            "[MOCK] Connection request already sent for this session. "
            "Call load_test_case to reset."
        )

    logger.info(
        "send_connection_request MOCK (test case: %s)  url=%s  note_len=%d",
        session.test_case_id, profile_url, len(note),
    )

    if session.connection_accepted:
        session.history.append({"message": note, "self": True})
        session.messages_sent = 1
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

    session.history.append({"message": message, "self": True})
    dm_index = session.messages_sent       # index into replies for this turn
    session.messages_sent += 1
    _append_prospect_reply(session, reply_index=dm_index)

    logger.info(
        "send_message MOCK (test case: %s)  url=%s  dm_index=%d  history_len=%d",
        session.test_case_id, profile_url, dm_index, len(session.history),
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
