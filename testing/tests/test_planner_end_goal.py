"""Unit tests for resolve_end_goal and planner stub behavior (no API)."""

import os
import sys

import pytest

# Core repo root (outreach.planner lives in the core, not testing/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

# Stub mode: ensure no API key so plan_message uses _plan_stub
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

from outreach.planner import plan_message, resolve_end_goal  # noqa: E402


def base_prospect(**overrides):
    p = {
        "id": "test_slug",
        "name": "Jamie Lee",
        "title": "Engineer",
        "linkedin_url": "https://www.linkedin.com/in/jamie-lee/",
        "outreach_stage": "cold",
        "recent_posts": [{"text": "Shipped a cache layer last week.", "likes": 3, "timestamp": "2026-01-01"}],
        "notes": "Met at conference.",
    }
    p.update(overrides)
    return p


def cold_conversation():
    return {
        "prospect_id": "test_slug",
        "outreach_stage": "cold",
        "next_action": "send_connection_request",
        "messages": [],
    }


@pytest.mark.parametrize(
    "prospect_kwargs,expected",
    [
        ({}, "schedule_meeting"),
        ({"end_goal": "none"}, "none"),
        ({"end_goal": "obtain_resume"}, "obtain_resume"),
        ({"target_action": "request_resume"}, "obtain_resume"),
        ({"target_action": "schedule_call"}, "schedule_meeting"),
        ({"end_goal": "schedule_meeting", "target_action": "request_resume"}, "schedule_meeting"),
    ],
)
def test_resolve_end_goal(prospect_kwargs, expected):
    assert resolve_end_goal(base_prospect(**prospect_kwargs)) == expected


def test_stub_connection_none_has_no_meeting_language():
    r = plan_message(
        base_prospect(end_goal="none", outreach_topic="old friends from college"),
        cold_conversation(),
    )
    assert r["action"] == "send_connection_request"
    m = r["message"].lower()
    assert "jamie" in m
    for bad in ("resume", "calendar", "quick call", "intro call", "15 min", "book"):
        assert bad not in m


def test_stub_followup_obtain_resume_mentions_resume():
    r = plan_message(
        base_prospect(end_goal="obtain_resume"),
        {**cold_conversation(), "next_action": "send_followup_message", "messages": [{"sender": "operator", "text": "hi", "timestamp": "2026-01-01T00:00:00Z"}]},
    )
    assert "resume" in r["message"].lower()


def test_stub_connection_request_char_cap():
    r = plan_message(base_prospect(), cold_conversation())
    assert len(r["message"]) <= 300
