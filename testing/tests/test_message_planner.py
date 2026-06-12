"""
Test harness for the Message Planner skill.

Tests message generation without any browser or LinkedIn access.
Works in two modes:
  - stub mode  (default): fully offline, no API key needed
  - API mode:             set ANTHROPIC_API_KEY to test against the real Claude model

Run with:
    uv run tests/test_message_planner.py                           # stub mode
    ANTHROPIC_API_KEY=sk-ant-... uv run tests/test_message_planner.py  # API mode
"""

import json
import os
import sys

# Make the project root importable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from outreach.planner import plan_message  # noqa: E402

PROSPECTS_DIR = os.path.join(BASE_DIR, "outreach", "prospects")
CONVOS_DIR    = os.path.join(BASE_DIR, "outreach", "conversations")
LOGS_DIR      = os.path.join(BASE_DIR, "outreach", "logs")

BANNED_PHRASES = [
    "i came across your profile",
    "i'd love to pick your brain",
    "synergy",
    "hope this message finds you",
    "reaching out to connect",
    "touching base",
]


# ── Validators ────────────────────────────────────────────────────────────────

def validate_message(result: dict, prospect: dict) -> list:
    failures = []
    msg    = result["message"].lower()
    action = result["action"]

    if action == "send_connection_request" and len(result["message"]) > 300:
        failures.append(f"Connection note too long: {len(result['message'])} chars (limit 300)")
    if action == "send_followup_message" and len(result["message"]) > 500:
        failures.append(f"Follow-up too long: {len(result['message'])} chars (limit 500)")

    for phrase in BANNED_PHRASES:
        if phrase in msg:
            failures.append(f"Banned phrase found: '{phrase}'")

    if not result["message"].strip():
        failures.append("Message is empty")

    first_name = prospect["name"].split()[0].lower()
    if first_name not in msg:
        failures.append(f"Message does not reference prospect's name ({first_name})")

    for field in ["prospect_id", "stage", "action", "message", "generated_at", "mode"]:
        if field not in result:
            failures.append(f"Missing output field: {field}")

    return failures


# ── Fixtures ──────────────────────────────────────────────────────────────────

def load_fixture(prospect_file: str, conversation_file: str):
    with open(os.path.join(PROSPECTS_DIR, prospect_file)) as f:
        prospect = json.load(f)
    with open(os.path.join(CONVOS_DIR, conversation_file)) as f:
        conversation = json.load(f)
    return prospect, conversation


def log_result(result: dict):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(os.path.join(LOGS_DIR, "planned_messages.jsonl"), "a") as f:
        f.write(json.dumps(result) + "\n")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_test(name: str, prospect_file: str, conversation_file: str) -> bool:
    print(f"\n{'─'*60}")
    print(f"TEST: {name}")
    print(f"  Prospect:     {prospect_file}")
    print(f"  Conversation: {conversation_file}")

    try:
        prospect, conversation = load_fixture(prospect_file, conversation_file)
        result   = plan_message(prospect, conversation)
        failures = validate_message(result, prospect)

        print(f"\n  Mode:    {result['mode']}")
        print(f"  Action:  {result['action']}")
        print(f"  Message ({len(result['message'])} chars):")
        print(f"  > {result['message']}")

        log_result(result)

        if failures:
            print(f"\n  ❌ FAIL — {len(failures)} issue(s):")
            for f in failures:
                print(f"     • {f}")
            return False

        print(f"\n  ✅ PASS")
        return True

    except Exception as e:
        print(f"\n  ❌ ERROR — {e}")
        import traceback; traceback.print_exc()
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = "API" if os.environ.get("ANTHROPIC_API_KEY") else "stub"
    print(f"Running in {mode} mode")

    tests = [
        ("Cold prospect — connection request",  "sample_alex_chen.json", "sample_alex_chen.json"),
        ("Replied prospect — follow-up message", "sample_alex_chen.json", "sample_alex_chen_replied.json"),
    ]

    results = [run_test(*t) for t in tests]

    total  = len(results)
    passed = sum(results)
    print(f"\n{'═'*60}")
    print(f"Results: {passed}/{total} passed")

    sys.exit(0 if passed == total else 1)
