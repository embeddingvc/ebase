"""
Message Planner — core module.

Two modes:
  - API mode:  ANTHROPIC_API_KEY is set → calls Claude API
  - Stub mode: no key → uses deterministic template (safe for offline tests)

Usage:
    from outreach.planner import plan_message

    result = plan_message(prospect_dict, conversation_dict)
    # result = { prospect_id, stage, action, message, generated_at, mode }
"""

import json
import os
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone

import certifi

# macOS + python.org builds don't bundle CA certs — use certifi's bundle.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# ── Prompt templates ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert recruiter writing personalized LinkedIn outreach messages.

Rules:
- Connection request notes must be ≤300 characters (LinkedIn hard limit — count carefully)
- Follow-up messages must be ≤500 characters
- Reference at least one specific detail from the prospect's recent posts or background
- Never use these phrases: "I came across your profile", "I'd love to pick your brain",
  "synergy", "hope this message finds you", "reaching out to connect", "touching base"
- Sound human and specific — not like a mass template
- You MUST open with or include the prospect's first name somewhere in the message
- Do not add any preamble or explanation — return only the message text itself
"""

def _build_user_prompt(prospect: dict, conversation: dict, action: str) -> str:
    recent_posts = prospect.get("recent_posts", [])
    posts_text = "\n".join(
        f'- "{p["text"][:120]}..." ({p["timestamp"]}, {p["likes"]} likes)'
        for p in recent_posts[:3]
    )

    prior_messages = conversation.get("messages", [])
    history_text = "\n".join(
        f'[{m["sender"]}] {m["text"]}'
        for m in prior_messages[-4:]
    ) or "(no prior messages)"

    first_name = prospect.get("name", "").split()[0]
    char_limit = 300 if action == "send_connection_request" else 500
    return f"""Generate a LinkedIn message for this action: {action.replace("_", " ")}
HARD LIMIT: {char_limit} characters maximum. Count carefully before responding.
The prospect's first name is "{first_name}" — you must use it in the message.

--- PROSPECT ---
Name:       {prospect.get("name")}
Title:      {prospect.get("title")}
Company:    {prospect.get("company")}
Location:   {prospect.get("location")}
Notes:      {prospect.get("notes", "")}

Recent posts:
{posts_text or "(none)"}

--- CONVERSATION HISTORY ---
{history_text}

--- TASK ---
Action:     {action}
Stage:      {prospect.get("outreach_stage", "cold")}

Write the message now. Return only the message text.
"""


# ── API planner ───────────────────────────────────────────────────────────────

def _plan_with_api(prospect: dict, conversation: dict, action: str) -> str:
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    )
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    payload = json.dumps({
        "model": model,
        "max_tokens": 256,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": _build_user_prompt(prospect, conversation, action)},
        ],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as r:
            return json.loads(r.read())["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic API error {e.code}: {e.read().decode()}")


# ── Stub planner (offline / testing) ─────────────────────────────────────────

def _plan_stub(prospect: dict, conversation: dict, action: str) -> str:
    name  = prospect["name"].split()[0]
    posts = prospect.get("recent_posts", [])
    hook  = posts[0]["text"][:60] if posts else prospect.get("notes", "your background")[:60]

    if action == "send_connection_request":
        return (
            f"Hey {name} — saw your recent post on {hook}... "
            "Building something in that space and your background stood out. Would love to connect."
        )[:300]

    if action == "send_followup_message":
        return (
            f"Thanks for connecting, {name}! "
            f"We're hiring for a role that maps closely to your {prospect.get('title', 'background')} experience. "
            "Would you be open to sharing your resume so I can pass it along to the team?"
        )[:500]

    return f"Hi {name}, following up — happy to answer any questions about the role."


# ── Public interface ──────────────────────────────────────────────────────────

def plan_message(prospect: dict, conversation: dict) -> dict:
    """
    Returns a planned message dict.
    Uses the Claude API if ANTHROPIC_API_KEY is set, otherwise falls back to the stub.
    """
    action = conversation.get("next_action", "send_connection_request")

    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        message = _plan_with_api(prospect, conversation, action)
        mode = "api"
    else:
        message = _plan_stub(prospect, conversation, action)
        mode = "stub"

    return {
        "prospect_id":  prospect["id"],
        "stage":        prospect.get("outreach_stage", "cold"),
        "action":       action,
        "message":      message,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode":         mode,
    }
