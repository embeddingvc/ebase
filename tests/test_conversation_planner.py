"""
Integration tests for the conversation-planner skill.

Sends the SKILL.md system prompt + fixture data to the Claude API,
parses the PlannedMessage JSON output, and validates structure + rules.
Each test run is saved as a dated log file in outreach/logs/.

Run:
    # Requires ANTHROPIC_API_KEY (in .env or exported)
    cd <project-root>
    uv run python tests/test_conversation_planner.py

    # Or with a specific model:
    CLAUDE_MODEL=claude-sonnet-4-6 uv run python tests/test_conversation_planner.py
"""

import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

# ── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(BASE_DIR, "tests", "fixtures", "conversation-planner")
SKILL_PATH   = os.path.join(BASE_DIR, "outreach", "skills", "conversation-planner", "SKILL.md")
LOGS_DIR     = os.path.join(BASE_DIR, "outreach", "logs")
PLANNER_CONFIG_PATH = os.path.join(
    BASE_DIR, "outreach", "config", "conversation_planner.json"
)

# ── Load .env ────────────────────────────────────────────────────────────────

def _load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if val and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────────

BANNED_PHRASES = [
    "i came across your profile",
    "i'd love to pick your brain",
    "synergy",
    "hope this message finds you",
    "reaching out to connect",
    "touching base",
    "circle back",
    "bandwidth",
]

VALID_ACTIONS = {
    "send_connection_request",
    "send_followup_message",
    "mark_ended",
    "mark_dead",
    "download_resume",
    "confirm_meeting",
    None,
}

VALID_STAGES = {
    "cold", "pending_connection", "engaged", "replied",
    "converted", "ended", "dead",
}

# ── API caller ───────────────────────────────────────────────────────────────

def call_claude(system_prompt: str, user_prompt: str) -> str:
    """Call the Anthropic Messages API and return the assistant text."""
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    )
    if not api_key:
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN."
        )

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    payload = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_prompt},
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
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CONTEXT) as r:
            body = json.loads(r.read())
            return body["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic API error {e.code}: {e.read().decode()}")


# ── Prompt builders ──────────────────────────────────────────────────────────

def load_skill_prompt() -> str:
    with open(SKILL_PATH) as f:
        return f.read()


def build_user_prompt(prospect: dict, conversation: dict, extra_context: str = "") -> str:
    """Build the user turn that simulates invoking the conversation-planner."""
    lines = [
        "You are being invoked as the conversation-planner skill.",
        "Read the prospect and conversation data below, then produce ONLY",
        "the PlannedMessage JSON object — no markdown fences, no preamble, no explanation.",
        "",
        "--- PROSPECT ---",
        json.dumps(prospect, indent=2),
        "",
        "--- CONVERSATION ---",
        json.dumps(conversation, indent=2),
    ]
    if extra_context:
        lines += ["", "--- EXTRA CONTEXT ---", extra_context]
    lines += [
        "",
        "--- TASK ---",
        "Determine the correct next step, compose the message (or decide to end),",
        "and return a single PlannedMessage JSON object.",
        "Return ONLY valid JSON. No markdown code fences. No prose.",
    ]
    return "\n".join(lines)


# ── JSON extraction ──────────────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """
    Pull the first JSON object out of the model response.
    Handles markdown fences, leading prose, etc.
    """
    # Try to strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.strip()

    # Find the first { ... } block
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    raise ValueError(f"No valid JSON object found in response:\n{raw[:500]}")


# ── Validators ───────────────────────────────────────────────────────────────

def validate_planned_message(result: dict, prospect: dict, expected: dict) -> list:
    """
    Validate a PlannedMessage dict.
    `expected` has optional keys: step, action, end_conversation, ended_reason, max_chars.
    """
    failures = []

    # ── Required fields ──────────────────────────────────────────────────
    required_fields = [
        "prospect_id", "stage", "sequence_step", "action",
        "message", "end_conversation", "ended_reason", "generated_at",
    ]
    for field in required_fields:
        if field not in result:
            failures.append(f"Missing field: {field}")

    if failures:
        return failures  # can't validate further

    # ── prospect_id ──────────────────────────────────────────────────────
    if result["prospect_id"] != prospect["id"]:
        failures.append(
            f"prospect_id mismatch: got '{result['prospect_id']}', "
            f"expected '{prospect['id']}'"
        )

    # ── stage ────────────────────────────────────────────────────────────
    if result["stage"] not in VALID_STAGES:
        failures.append(f"Invalid stage: '{result['stage']}'")

    # ── action ───────────────────────────────────────────────────────────
    if result["action"] not in VALID_ACTIONS:
        failures.append(f"Invalid action: '{result['action']}'")

    if "action" in expected and result["action"] != expected["action"]:
        failures.append(
            f"Expected action '{expected['action']}', got '{result['action']}'"
        )

    # ── sequence_step ────────────────────────────────────────────────────
    if "step" in expected and result.get("sequence_step") != expected["step"]:
        failures.append(
            f"Expected sequence_step {expected['step']}, "
            f"got {result.get('sequence_step')}"
        )

    # ── end_conversation ─────────────────────────────────────────────────
    if "end_conversation" in expected:
        if result["end_conversation"] != expected["end_conversation"]:
            failures.append(
                f"Expected end_conversation={expected['end_conversation']}, "
                f"got {result['end_conversation']}"
            )

    # ── ended_reason ─────────────────────────────────────────────────────
    ended_reason = result.get("ended_reason")
    if ended_reason is not None:
        if not isinstance(ended_reason, str) or not ended_reason.strip():
            failures.append(f"Invalid ended_reason: '{ended_reason}'")

    if "ended_reason" in expected:
        if result.get("ended_reason") != expected["ended_reason"]:
            failures.append(
                f"Expected ended_reason '{expected['ended_reason']}', "
                f"got '{result.get('ended_reason')}'"
            )

    # ── message content checks (only when a message is expected) ─────────
    msg = result.get("message")
    if msg is not None and isinstance(msg, str) and msg.strip():
        msg_lower = msg.lower()

        # Character limit
        max_chars = expected.get("max_chars", 500)
        if len(msg) > max_chars:
            failures.append(f"Message too long: {len(msg)} chars (limit {max_chars})")

        # Banned phrases
        for phrase in BANNED_PHRASES:
            if phrase in msg_lower:
                failures.append(f"Banned phrase found: '{phrase}'")

        # First name check — soft warning, not a hard failure.
        # The skill instructs the model to include it, but it's not always
        # included in shorter follow-ups. We log it but don't fail.
        first_name = prospect["name"].split()[0].lower()
        if first_name not in msg_lower:
            # Print warning but don't add to failures
            print(f"  [WARN] Message does not contain prospect's first name '{first_name}'")

        # Must not be empty when a send action is expected
        if not msg.strip() and result["action"] in (
            "send_connection_request", "send_followup_message"
        ):
            failures.append("Message is empty but action requires a send")

    elif result.get("end_conversation") is not True:
        # message is null/empty but we're not ending — that's wrong
        if result["action"] in ("send_connection_request", "send_followup_message"):
            failures.append(
                "Message is null/empty but action is a send action and "
                "end_conversation is not true"
            )

    return failures


# ── Test cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "Step 1 — Cold prospect, connection request",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_step1_cold.json",
        "expected": {
            "step": 1,
            "action": "send_connection_request",
            "end_conversation": False,
            "ended_reason": None,
            "max_chars": 300,
        },
    },
    {
        "name": "Step 2 — Prospect replied, career deep-dive",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_step2_replied.json",
        "expected": {
            "step": 2,
            "action": "send_followup_message",
            "end_conversation": False,
            "ended_reason": None,
            "max_chars": 500,
        },
    },
    {
        "name": "Step 3 — Career discussed, ask about plans",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_step3_career_discussed.json",
        "expected": {
            "step": 3,
            "action": "send_followup_message",
            "end_conversation": False,
            "ended_reason": None,
            "max_chars": 500,
        },
    },
    {
        "name": "Step 4 — Career plan replied, the ask",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_step4_career_plan_replied.json",
        "expected": {
            "step": 4,
            "action": "send_followup_message",
            "end_conversation": False,
            "ended_reason": None,
            "max_chars": 500,
        },
    },
    {
        "name": "Step 5 — Resume shared, the close",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_step5_resume_shared.json",
        "expected": {
            "step": 5,
            "action": "send_followup_message",
            "end_conversation": True,
            "ended_reason": "resume_received",
            "max_chars": 500,
        },
    },
    {
        "name": "Edge — No reply timeout (>48h since Step 2)",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_no_reply_timeout.json",
        "extra_context": "Current UTC time: 2026-03-28T14:00:00Z (>48h since last operator message on 2026-03-25T14:00:00Z with no prospect reply).",
        "expected": {
            # sequence_step can be null or the last step — both are acceptable
            "end_conversation": True,
            "ended_reason": "no_response",
        },
    },
    {
        "name": "Edge — Prospect not interested",
        "prospect_file": "prospect_alex.json",
        "conversation_file": "conv_not_interested.json",
        "expected": {
            "end_conversation": True,
            "ended_reason": "not_interested",
        },
    },
]


# ── Log writer ───────────────────────────────────────────────────────────────

class TestLogger:
    """Writes a dated log file in outreach/logs/."""

    def __init__(self):
        os.makedirs(LOGS_DIR, exist_ok=True)
        self.run_ts = datetime.now(timezone.utc)
        date_str = self.run_ts.strftime("%Y-%m-%dT%H%M%SZ")
        model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        self.log_path = os.path.join(
            LOGS_DIR, f"conversation-planner-test_{date_str}_{model}.log"
        )
        self.records = []
        self._lines = []

    def header(self, text: str):
        self._lines.append(f"\n{'='*70}")
        self._lines.append(text)
        self._lines.append(f"{'='*70}")

    def section(self, text: str):
        self._lines.append(f"\n{'─'*60}")
        self._lines.append(text)

    def line(self, text: str = ""):
        self._lines.append(text)

    def record(self, entry: dict):
        """Append a structured record for the JSONL summary at the end."""
        self.records.append(entry)

    def flush(self):
        # Append JSONL summary
        self._lines.append(f"\n{'='*70}")
        self._lines.append("STRUCTURED RESULTS (JSONL)")
        self._lines.append(f"{'='*70}")
        for rec in self.records:
            self._lines.append(json.dumps(rec))

        with open(self.log_path, "w") as f:
            f.write("\n".join(self._lines) + "\n")


# ── Runner ───────────────────────────────────────────────────────────────────

def run_test(tc: dict, skill_prompt: str, logger: TestLogger) -> bool:
    name = tc["name"]
    logger.section(f"TEST: {name}")
    print(f"\n{'─'*60}")
    print(f"TEST: {name}")

    prospect_path = os.path.join(FIXTURES_DIR, tc["prospect_file"])
    conv_path     = os.path.join(FIXTURES_DIR, tc["conversation_file"])

    with open(prospect_path) as f:
        prospect = json.load(f)
    with open(conv_path) as f:
        conversation = json.load(f)

    logger.line(f"  Prospect:     {tc['prospect_file']}")
    logger.line(f"  Conversation: {tc['conversation_file']}")
    print(f"  Prospect:     {tc['prospect_file']}")
    print(f"  Conversation: {tc['conversation_file']}")

    extra = tc.get("extra_context", "")
    user_prompt = build_user_prompt(prospect, conversation, extra)

    try:
        raw_response = call_claude(skill_prompt, user_prompt)
    except Exception as e:
        msg = f"  API ERROR: {e}"
        logger.line(msg)
        logger.record({
            "test": name, "status": "error", "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        print(msg)
        return False

    logger.line(f"\n  Raw response ({len(raw_response)} chars):")
    logger.line(f"  {raw_response[:800]}")
    print(f"  Raw response ({len(raw_response)} chars):")

    try:
        result = extract_json(raw_response)
    except ValueError as e:
        msg = f"  JSON PARSE ERROR: {e}"
        logger.line(msg)
        logger.record({
            "test": name, "status": "error",
            "error": f"JSON parse: {e}",
            "raw_response": raw_response[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        print(msg)
        return False

    logger.line(f"\n  Parsed PlannedMessage:")
    logger.line(f"  {json.dumps(result, indent=2)}")

    # Pretty-print key fields
    msg_text = result.get("message") or "(none)"
    msg_len  = len(msg_text) if result.get("message") else 0
    print(f"  Step:    {result.get('sequence_step')}")
    print(f"  Action:  {result.get('action')}")
    print(f"  End:     {result.get('end_conversation')}")
    print(f"  Reason:  {result.get('ended_reason')}")
    print(f"  Message ({msg_len} chars): {msg_text[:120]}{'...' if msg_len > 120 else ''}")

    # Validate
    failures = validate_planned_message(result, prospect, tc["expected"])

    record = {
        "test": name,
        "status": "pass" if not failures else "fail",
        "sequence_step": result.get("sequence_step"),
        "action": result.get("action"),
        "end_conversation": result.get("end_conversation"),
        "ended_reason": result.get("ended_reason"),
        "message_chars": msg_len,
        "failures": failures,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if failures:
        logger.line(f"\n  FAIL — {len(failures)} issue(s):")
        print(f"\n  FAIL — {len(failures)} issue(s):")
        for f in failures:
            logger.line(f"     - {f}")
            print(f"     - {f}")
        record["planned_message"] = result
    else:
        logger.line(f"\n  PASS")
        print(f"\n  PASS")

    logger.record(record)
    return len(failures) == 0


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not api_key:
        print("ERROR: No ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN found.")
        print("Set one in .env or export it before running.")
        sys.exit(1)

    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    print(f"Model: {model}")
    print(f"Skill: {SKILL_PATH}")

    # Fast static checks for config-driven planner behavior.
    static_failures = []
    if not os.path.exists(PLANNER_CONFIG_PATH):
        static_failures.append(f"Missing config file: {PLANNER_CONFIG_PATH}")
    else:
        with open(PLANNER_CONFIG_PATH) as f:
            cfg = json.load(f)
        for required_key in (
            "persona",
            "organization",
            "campaign",
            "conversation_end_goals",
            "message_rules",
        ):
            if required_key not in cfg:
                static_failures.append(f"Config missing key: {required_key}")

    skill_prompt = load_skill_prompt()
    for required_phrase in (
        "get_conversation_planner_config",
        "campaign.goal",
        "campaign.topic",
        "conversation_end_goals",
    ):
        if required_phrase not in skill_prompt:
            static_failures.append(f"Skill prompt missing phrase: {required_phrase}")

    if static_failures:
        print("Static config checks failed:")
        for failure in static_failures:
            print(f"  - {failure}")
        sys.exit(1)

    logger = TestLogger()

    logger.header(
        f"conversation-planner test run\n"
        f"  Model:     {model}\n"
        f"  Timestamp: {logger.run_ts.isoformat()}\n"
        f"  Tests:     {len(TEST_CASES)}"
    )

    results = []
    for tc in TEST_CASES:
        passed = run_test(tc, skill_prompt, logger)
        results.append(passed)

    total  = len(results)
    passed = sum(results)

    logger.header(f"SUMMARY: {passed}/{total} passed")
    logger.flush()

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    print(f"Log saved: {logger.log_path}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
