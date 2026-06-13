"""
Local regression harness: models the real operator pipeline order:

1. **LinkedIn connection** — Harness calls MCP ``send_connection_request`` (mock-backed) plus
   ``upsert_prospect`` / ``save_connection`` with ``pending`` after ``handle_load_test_case``
   (same as prod / operator pipeline).
2. **Connection sync** — direct in-process call to the deterministic Python sweep
   (``cron.connection_sync_sweep.run_sync_sweep``) using a mock-backed probe. This
   replaces the former ``sync-pending-connections`` ``claude -p`` invocation,
   which has been retired in favour of the LLM-free dashboard sweep.
3. **conversation-planner rounds** — ``claude -p`` runs **conversation-planner**
   in **single-prospect mode** (``prospect_id`` supplied). The skill no longer
   supports batch mode, so the harness drives one prospect per round explicitly.
   The harness still applies ``send_*`` from the parsed PlannedMessage and
   snapshots ``upsert_conversation`` from the mock thread (plan-only inside
   ``claude -p`` avoids double delivery).

The mock-capable MCP (``testing/tools/server.py``) is used in-process so paths
follow ``_outreach_base()`` (``testing/outreach/mock/`` in mock mode).

See: ``docs/designs/outreach-workflow-regression-tests-design.md``,
``docs/designs/schedule-meeting-mcp-and-regression-design.md``,
``docs/designs/per-connection-routines-with-backoff-design.md``
"""

from __future__ import annotations

import asyncio
import json
import logging
from math import exp
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("outreach.regression")

TESTING_ROOT = Path(__file__).resolve().parent.parent  # testing/
CORE_ROOT = TESTING_ROOT.parent                         # core repo root
_TOOLS = TESTING_ROOT / "tools"
for _p in (str(CORE_ROOT), str(TESTING_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mock as _mock  # noqa: E402  — testing/tools/mock.py
from outreach.mock.fixtures_loader import (  # noqa: E402
    get_fixture,
    load_regression_specs,
)

FIXTURES = TESTING_ROOT / "tests" / "fixtures" / "conversation-planner"
PROSPECT_FIXTURE = FIXTURES / "prospect_alex.json"

# Installed skill ids (see outreach/skills/*/SKILL.md frontmatter ``name``).
CONVERSATION_PLANNER_SKILL = "conversation-planner"
# ``sync-pending-connections`` skill has been retired; the deterministic sweep
# in ``cron.connection_sync_sweep`` is what the scheduler uses now.

# Canonical profile URL for mock sessions (matches prospect_alex.json).
REGRESSION_PROFILE_URL = "https://www.linkedin.com/in/alex-chen-softeng/"
PROSPECT_ID = "alex_chen_softeng"

_SERVER_MODULE: Any = None


def get_server_module() -> Any:
    """Load ``testing/tools/server.py`` once (mock MCP tool implementations + paths)."""
    global _SERVER_MODULE
    if _SERVER_MODULE is not None:
        return _SERVER_MODULE
    import importlib.util

    path = TESTING_ROOT / "tools" / "server.py"
    spec = importlib.util.spec_from_file_location("linkedin_mcp_server_regression", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load server spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SERVER_MODULE = mod
    return mod


def extract_json_object(raw: str) -> dict[str, Any]:
    """Return the first JSON object embedded in *raw* (handles markdown fences, prose)."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = cleaned.strip()
    depth = 0
    start: int | None = None
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
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue
    raise ValueError(f"No valid JSON object found in response:\n{raw[:500]}")


def parse_planned_message(stdout: str) -> dict[str, Any]:
    """Parse a :class:`PlannedMessage`-shaped dict from model stdout."""
    obj = extract_json_object(stdout)
    if not obj.get("action"):
        raise ValueError("PlannedMessage missing required field: action")
    return obj


def _utc_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _normalize_attachments(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for a in raw:
        if not isinstance(a, dict):
            continue
        t = a.get("type")
        if t not in ("resume", "image", "link", "document"):
            continue
        item: dict[str, Any] = {"type": t}
        if "url" in a:
            item["url"] = a.get("url")
        if "filename" in a:
            item["filename"] = a.get("filename")
        out.append(item)
    return out


async def _run_regression_connection_sync(mod: Any, profile_url: str) -> None:
    """Drive the deterministic connection sync sweep against the mock target.

    Mirrors what the cron scheduler does in production
    (``cron.routine_scheduler._run_sync_sweep_routine``) but with a probe
    that calls the in-process mock handler so we don't need a browser.

    ``cron.connection_sync_sweep`` resolves its data root via
    ``outreach.data_paths.outreach_base()``, which is independent of the mock
    MCP's ``_outreach_base()``. In mock mode the server writes to
    ``testing/outreach/mock/`` while the core helper defaults to ``outreach/``
    unless ``OUTREACH_DATA_ROOT`` is set, so the sweep would otherwise load the
    wrong ``connections.json`` and never see the pending row. Pin
    ``OUTREACH_DATA_ROOT`` to the server's base for the duration of the sweep
    so both halves agree.
    """
    from cron.connection_sync_sweep import run_sync_sweep

    async def _probe(url: str) -> bool | str:
        raw = await mod.is_first_degree_connection(url)
        try:
            return bool(json.loads(raw).get("first_degree", False))
        except (json.JSONDecodeError, AttributeError, TypeError):
            return raw if isinstance(raw, str) else f"error: bad probe response: {raw!r}"

    rcfg = {
        "active": True,
        "active_window_start": None,
        "active_window_end": None,
        "backoff": {
            "initial_minutes": 1,
            "multiplier": 1.0,
            "max_minutes": 1,
            "error_jitter": False,
        },
    }
    base_path = str(mod._outreach_base())
    prev_root = os.environ.get("OUTREACH_DATA_ROOT")
    os.environ["OUTREACH_DATA_ROOT"] = base_path
    try:
        await run_sync_sweep(rcfg, probe=_probe)
    finally:
        if prev_root is None:
            os.environ.pop("OUTREACH_DATA_ROOT", None)
        else:
            os.environ["OUTREACH_DATA_ROOT"] = prev_root
    del profile_url  # silence unused — the sweep walks all pending rows


async def reset_regression_artifacts(mod: Any, profile_url: str, prospect_id: str) -> None:
    """Clear mock session state and on-disk mock outreach rows for a clean scenario run."""
    key = _mock.normalise_url(profile_url)
    _mock.sessions.pop(key, None)
    _mock.clear_persisted_mock_session(profile_url)
    base: Path = mod._outreach_base()
    mod._atomic_write_json(base / "connections.json", {"connections": []})
    conv_path = base / "conversations" / f"{prospect_id}.json"
    if conv_path.is_file():
        conv_path.unlink()
    prospect_path = base / "prospects" / f"{prospect_id}.json"
    if prospect_path.is_file():
        prospect_path.unlink()


async def seed_regression_mock_session(case_id: str, profile_url: str) -> None:
    """Load the scripted ``TEST_CASES`` scenario into the in-memory mock session."""
    raw = await _mock.handle_load_test_case(case_id, profile_url)
    if isinstance(raw, str) and raw.startswith("Unknown test case"):
        raise RuntimeError(f"load test case failed: {raw}")


def _messages_from_mock_session(
    session: _mock.MockSession, *, base: datetime
) -> list[dict[str, Any]]:
    """Map mock ``fetch_chat_history`` rows to conversation-schema messages."""
    out: list[dict[str, Any]] = []
    op_count = 0
    for i, entry in enumerate(session.history):
        self_flag = bool(entry.get("self"))
        sender = "operator" if self_flag else "prospect"
        item: dict[str, Any] = {
            "sender": sender,
            "text": str(entry.get("message") or ""),
            "timestamp": _utc_ts(base + timedelta(minutes=i + 1)),
            "attachments": _normalize_attachments(entry.get("attachments")),
        }
        if self_flag:
            op_count += 1
            item["sequence_step"] = op_count
        else:
            item["sequence_step"] = None
        out.append(item)
    return out


async def seed_regression_prospect(
    mod: Any, case_id: str, profile_url: str, prospect_id: str
) -> None:
    """Materialize a prospect row from the mock TEST_CASES fixture.

    ``send-connection-request`` may write ``connections.json`` but often skips
    ``prospects/<id>.json``. The conversation-planner skill (single-prospect
    mode) requires ``get_prospect`` to succeed, so the harness seeds that file
    from the same scripted prospect data ``scrape_profile`` would return for
    this case in mock mode — before the connect step, matching production
    where scrape/parse runs upstream of the invite.
    """
    tc = _mock.TEST_CASES[case_id]
    fixture: dict[str, Any] = dict(tc.get("prospect") or {})
    prospect = {
        "id": prospect_id,
        "linkedin_url": profile_url,
        "name": fixture.get("name") or "Prospect",
        "title": fixture.get("title"),
        "company": fixture.get("company"),
        "location": fixture.get("location"),
        "connection_degree": fixture.get("connection_degree", 2),
        "mutual_connections": list(fixture.get("mutual_connections") or []),
        "recent_posts": list(fixture.get("recent_posts") or []),
        "connection_status": "pending",
        "outreach_stage": "pending_connection",
        "end_goal": "schedule_meeting",
        "outreach_topic": "Series A ML infra roles in the portfolio",
        "notes": fixture.get("about"),
        "profile_fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    raw = await mod.upsert_prospect(prospect_id, json.dumps(prospect))
    if isinstance(raw, str) and raw.startswith("error:"):
        raise RuntimeError(f"seed prospect failed: {raw}")


async def sync_regression_prospect_after_sync(
    mod: Any,
    prospect_id: str,
    *,
    connection_accepted: bool,
) -> None:
    """Refresh prospect pipeline fields after the connection-sync sweep."""
    raw = await mod.get_prospect(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        raise RuntimeError(f"sync prospect after sync failed: {raw}")
    prospect = json.loads(raw)
    if connection_accepted:
        prospect["connection_status"] = "connected"
        prospect["outreach_stage"] = "engaged"
    else:
        prospect["connection_status"] = "pending"
        prospect["outreach_stage"] = "pending_connection"
    raw = await mod.upsert_prospect(prospect_id, json.dumps(prospect))
    if isinstance(raw, str) and raw.startswith("error:"):
        raise RuntimeError(f"sync prospect after sync upsert failed: {raw}")


async def seed_regression_conversation_from_mock(
    mod: Any,
    profile_url: str,
    prospect_id: str,
    *,
    connection_accepted: bool,
) -> None:
    """Persist ``conversations/<id>.json`` from the live mock DM thread.

    The ``claude -p`` connect and planner invocations do not reliably call
    ``upsert_conversation``. This mirrors what ``send-connection-request`` and
    the planner's Phase A sync would have written: messages from
    ``fetch_chat_history``, stage aligned with ``connections.json``, and
    campaign snapshots from the seeded prospect.
    """
    session = _mock.get_session(profile_url)
    if session is None:
        raise RuntimeError(f"seed conversation: no mock session for {profile_url!r}")

    row = await _connection_row(mod, profile_url)
    conn_status = (row or {}).get("connection_status") or "pending"
    note_sent = (row or {}).get("note_sent")

    now = datetime.now(timezone.utc)
    messages = _messages_from_mock_session(session, base=now - timedelta(hours=2))
    has_prospect_reply = any(not h.get("self") for h in session.history)
    op_messages = [m for m in messages if m.get("sender") == "operator"]

    if conn_status == "connected" or connection_accepted:
        stage = "engaged"
    elif conn_status == "pending":
        stage = "pending_connection"
    else:
        stage = "cold"

    stage_history: list[dict[str, Any]] = [
        {
            "stage": "cold",
            "entered_at": _utc_ts(now - timedelta(days=1)),
            "reason": "regression seed",
        },
    ]
    if stage in ("pending_connection", "engaged"):
        stage_history.append(
            {
                "stage": "pending_connection",
                "entered_at": _utc_ts(now - timedelta(hours=3)),
                "reason": "connection request sent",
            }
        )
    if stage == "engaged":
        stage_history.append(
            {
                "stage": "engaged",
                "entered_at": _utc_ts(now - timedelta(hours=1)),
                "reason": "connection accepted",
            }
        )
    if has_prospect_reply and stage == "engaged":
        stage_history.append(
            {
                "stage": "replied",
                "entered_at": _utc_ts(now - timedelta(minutes=30)),
                "reason": "prospect replied positively",
            }
        )

    last_action_ts = (
        messages[-1]["timestamp"]
        if messages
        else _utc_ts(now - timedelta(hours=3))
    )
    conversation: dict[str, Any] = {
        "prospect_id": prospect_id,
        "outreach_stage": stage,
        "messages": messages,
        "last_action": "send_connection_request" if op_messages or note_sent else None,
        "last_action_timestamp": last_action_ts,
        "next_action": None,
        "next_action_after": None,
        "planned_message": None,
        "connection_note": note_sent,
        "end_goal": "schedule_meeting",
        "outreach_topic": "Series A ML infra roles in the portfolio",
        "resume_path": None,
        "email": None,
        "meeting_link": None,
        "ended_at": None,
        "ended_reason": None,
        "report_path": None,
        "sequence_step": op_messages[-1].get("sequence_step") if op_messages else None,
        "stage_history": stage_history,
    }
    raw = await mod.upsert_conversation(prospect_id, json.dumps(conversation))
    if isinstance(raw, str) and raw.startswith("error:"):
        raise RuntimeError(f"seed conversation failed: {raw}")


def claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        logger.warning("regression: could not read %s", path)
        return None


async def _connection_row(mod: Any, profile_url: str) -> dict[str, Any] | None:
    raw = await mod.get_connections()
    data = _load_json(TESTING_ROOT / "outreach" / "mock" / "connections.json")
    for row in data.get("connections") or []:
        if isinstance(row, dict) and row.get("profile_url") == profile_url:
            return row
    return None


async def assert_state_after_linkedin_connect(
    mod: Any, profile_url: str, prospect_name: str
) -> None:
    import pytest

    row = await _connection_row(mod, profile_url)
    if row is None:
        pytest.fail("post-connect: missing connections.json row")
    if row.get("connection_status") != "pending":
        pytest.fail(
            f"post-connect: expected pending got {row.get('connection_status')!r}"
        )
    if prospect_name and prospect_name not in (row.get("name") or ""):
        pytest.fail(
            f"post-connect: name mismatch row={row.get('name')!r} "
            f"expected substring {prospect_name!r}"
        )


async def assert_state_after_sync_pending(
    mod: Any,
    case_id: str,
    profile_url: str,
    connection_accepted: bool,
) -> None:
    import pytest

    row = await _connection_row(mod, profile_url)
    if row is None:
        pytest.fail("post-sync: missing connection row")
    st = row.get("connection_status")
    if connection_accepted:
        if st != "connected":
            pytest.fail(
                f"post-sync: expected connected for case {case_id!r}, got {st!r}"
            )
    else:
        if st != "pending":
            pytest.fail(
                f"post-sync: expected pending for non-accept case {case_id!r}, got {st!r}"
            )


async def assert_state_after_planner_round(
    mod: Any,
    profile_url: str,
    prospect_id: str,
    allowed_stages: set[str],
    session: _mock.MockSession,
) -> None:
    import pytest

    raw = await mod.get_conversation(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        pytest.fail(f"get_conversation failed: {raw}")
    conv = json.loads(raw)
    if conv.get("outreach_stage") not in allowed_stages:
        pytest.fail(
            f"post-planner: allowed_stages={allowed_stages!r} got {conv.get('outreach_stage')!r}"
        )


async def assert_connection_ended_when_conversation_terminal(
    mod: Any,
    profile_url: str,
    prospect_id: str,
) -> None:
    """After a terminal conversation, connections.json must show connection_status ended."""
    import pytest

    raw = await mod.get_conversation(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        return
    conv = json.loads(raw)
    if conv.get("outreach_stage") not in ("ended", "dead"):
        return
    row = await _connection_row(mod, profile_url)
    if row is None:
        pytest.fail("terminal conversation: missing connections.json row")
    if row.get("connection_status") != "ended":
        pytest.fail(
            f"terminal conversation: expected connection_status 'ended', "
            f"got {row.get('connection_status')!r}"
        )


def invoke_claude_cli(prompt: str) -> str:
    """
    Run ``claude -p`` from repo root with default tools so **MCP** (and skills) work.

    Permission mode defaults to ``bypassPermissions`` so non-interactive regression
    can call MCP tools; override with ``REGRESSION_CLAUDE_PERMISSION_MODE``.

    Model defaults to Haiku 4.5 (cheaper, separate quota from Sonnet/Opus).
    Set ``CLAUDE_MODEL`` (same as ``outreach/planner.py``) or pass ``--model haiku``
    aliases supported by the Claude CLI.
    """
    timeout = int(os.environ.get("REGRESSION_CLAUDE_TIMEOUT_SEC", "600"))
    perm = os.environ.get("REGRESSION_CLAUDE_PERMISSION_MODE", "bypassPermissions").strip()
    model = os.environ.get("CLAUDE_MODEL", "haiku").strip()
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--permission-mode",
        perm,
    ]
    env = os.environ.copy()
    home = env.get("HOME", "")
    env["PATH"] = f"{home}/.local/bin:{home}/.cargo/bin:{env.get('PATH', '')}"

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(CORE_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "claude executable not found (PATH). Install Claude Code CLI."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude subprocess exceeded timeout={timeout}s") from exc
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited {proc.returncode}. stdout+stderr tail:\n{out[-4000:]}"
        )
    return proc.stdout or ""

# Transition specs: loaded from outreach/mock/fixtures/*.json
RoundSpec = dict[str, Any]

REGRESSION_SPECS: dict[str, dict[str, Any]] = load_regression_specs()


def assert_transition(
    spec: RoundSpec,
    plan: dict[str, Any],
    *,
    round_index: int,
) -> None:
    import pytest

    rid = spec["id"]
    action = plan.get("action")
    allowed = spec["allowed_actions"]
    if action not in allowed:
        pytest.fail(
            f"transition[{rid}] round={round_index}: action={action!r} "
            f"not in allowed={sorted(allowed)}"
        )
    stages = spec.get("allowed_stages")
    if stages is not None:
        stage = plan.get("stage")
        if stage not in stages:
            pytest.fail(
                f"transition[{rid}] round={round_index}: stage={stage!r} "
                f"not in allowed={sorted(stages)}"
            )


def _prospect_has_resume_in_history(session: _mock.MockSession) -> bool:
    for e in session.history:
        if e.get("self"):
            continue
        for a in e.get("attachments") or []:
            if isinstance(a, dict) and a.get("type") == "resume":
                return True
    return False


def _prospect_email_in_history(session: _mock.MockSession) -> str | None:
    email_re = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
    for entry in session.history:
        if entry.get("self"):
            continue
        match = email_re.search(entry.get("message") or "")
        if match:
            return match.group(0)
    return None


async def assert_meeting_scheduled(
    mod: Any,
    prospect_id: str,
    *,
    profile_url: str | None = None,
) -> None:
    import pytest

    if profile_url:
        await apply_regression_schedule_fallback(mod, profile_url, prospect_id)
    raw = await mod.get_conversation(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        pytest.fail(f"assert_meeting_scheduled: get_conversation failed: {raw}")
    conv = json.loads(raw)
    if not conv.get("meeting_link"):
        pytest.fail("expected meeting_link after schedule_meeting")
    if not conv.get("email"):
        pytest.fail("expected email on conversation")


async def promote_connection_ended_from_conversation(
    mod: Any,
    profile_url: str,
    prospect_id: str,
) -> None:
    """
    When the model ends the conversation but skips save_connection(ended),
    mirror server upsert_conversation side effects for regression stability.
    """
    raw = await mod.get_conversation(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        return
    conv = json.loads(raw)
    if conv.get("outreach_stage") not in ("ended", "dead"):
        return
    row = await _connection_row(mod, profile_url)
    if row is None or row.get("connection_status") == "ended":
        return
    result = await mod.save_connection(
        profile_url=profile_url,
        name=row.get("name") or "Unknown",
        title=row.get("title") or "",
        prospect_id=prospect_id,
        note_sent=row.get("note_sent"),
        connection_status="ended",
    )
    if isinstance(result, str) and result.startswith("error:"):
        import pytest

        pytest.fail(f"promote_connection_ended_from_conversation failed: {result}")


async def apply_regression_schedule_fallback(
    mod: Any,
    profile_url: str,
    prospect_id: str,
) -> None:
    """Book via MCP when the mock thread has an email but no ``meeting_link`` yet.

    The planner often skips ``schedule_meeting`` even after the scripted
    ``happy_path`` reply[4] shares an address. Default **on** for regression
    stability; set ``REGRESSION_APPLY_SCHEDULE=0`` to disable.
    """
    flag = os.environ.get("REGRESSION_APPLY_SCHEDULE", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return
    session = _mock.get_session(profile_url)
    if session is None:
        return
    email = _prospect_email_in_history(session)
    if not email:
        return
    raw = await mod.get_conversation(prospect_id)
    if isinstance(raw, str) and raw.startswith("error:"):
        conv: dict[str, Any] = {}
    else:
        conv = json.loads(raw)
    if conv.get("meeting_link"):
        return
    result = await mod.schedule_meeting(
        email=email,
        datetime="2026-06-10T15:00:00Z",
        prospect_id=prospect_id,
        profile_url=profile_url,
    )
    if isinstance(result, str) and result.startswith("error:"):
        import pytest

        pytest.fail(f"regression schedule fallback failed: {result}")


def scenario_terminal_satisfied(case_id: str, session: _mock.MockSession, plan: dict[str, Any]) -> bool:
    if plan.get("end_conversation") or plan.get("action") in ("mark_ended", "mark_dead"):
        return True

    fixture = get_fixture(case_id) or {}
    terminal = fixture.get("terminal") or {}

    ended_reason = plan.get("ended_reason")
    if terminal.get("ended_reason") and ended_reason == terminal.get("ended_reason"):
        return True
    if ended_reason in (terminal.get("ended_reasons") or []):
        return True

    if terminal.get("require_resume_attachment") and _prospect_has_resume_in_history(session):
        return True

    phrase = terminal.get("prospect_phrase")
    if phrase:
        needle = str(phrase).lower()
        for entry in session.history:
            if entry.get("self"):
                continue
            if needle in (entry.get("message") or "").lower():
                actions = terminal.get("accept_actions") or ["mark_dead", "mark_ended"]
                if plan.get("action") in actions:
                    return True
                if ended_reason == terminal.get("ended_reason"):
                    return True

    accept_actions = terminal.get("accept_actions")
    if accept_actions and plan.get("action") in accept_actions:
        return True

    return False


async def run_scenario_async(case_id: str) -> None:
    """
    End-to-end sequence for one ``TEST_CASES`` entry:

    1. LinkedIn invite: ``send_connection_request`` + ``upsert_prospect`` + ``save_connection`` (pending).
    2. sync-pending-connections: ``get_connections`` → ``is_first_degree_connection`` → ``save_connection`` (connected when mock accepts).
    3. Persist ``upsert_conversation`` from mock thread, then conversation-planner rounds (``claude -p`` + MCP deliveries).
    """
    import pytest

    if case_id not in _mock.TEST_CASES:
        pytest.fail(f"unknown TEST_CASE case_id={case_id!r}")
    if case_id not in REGRESSION_SPECS:
        pytest.fail(f"no REGRESSION_SPECS for case_id={case_id!r}")

    mod = get_server_module()

    # Hard guard: never run the regression against live LinkedIn. The mock
    # path returns scripted responses from ``testing/tools/mock.py`` and writes to
    # ``testing/outreach/mock/``; live mode would talk to the real browser session
    # and corrupt the operator's connection list.
    if not mod._mock_mcp_enabled():
        pytest.fail(
            "Regression requires mock MCP mode. "
            "Run `make -C testing regression` (sets OUTREACH_MOCK=1) or export "
            "OUTREACH_MOCK=1 and register testing/tools/server.py with Claude."
        )

    url = REGRESSION_SPECS[case_id].get("profile_url") or REGRESSION_PROFILE_URL
    prospect_id = REGRESSION_SPECS[case_id].get("prospect_id") or PROSPECT_ID
    tc = _mock.TEST_CASES[case_id]
    connection_accepted = bool(tc.get("connection_accepted"))
    prospect_name = str((tc.get("prospect") or {}).get("name") or "Alex")

    await reset_regression_artifacts(mod, url, prospect_id)
    await seed_regression_mock_session(case_id, url)

    # Prospect scrape happens before connect in production; seed it here so
    # ``send-connection-request`` / ``conversation-planner`` always find the row
    # even when ``claude -p`` skips ``upsert_prospect``.
    await seed_regression_prospect(mod, case_id, url, prospect_id)

    invoke_claude_cli(f"Connect to {url}")
    await assert_state_after_linkedin_connect(mod, url, prospect_name)

    # The former "Run sync-pending-connections skill" claude -p invocation is
    # gone — the dashboard now performs this sweep in pure Python. Drive the
    # same code path directly so the regression matches production behaviour.
    try:
        await _run_regression_connection_sync(mod, url)
    except Exception as exc:
        pytest.fail(f"connection sync sweep (in-process): {exc}")

    await assert_state_after_sync_pending(mod, case_id, url, connection_accepted)
    await sync_regression_prospect_after_sync(
        mod, prospect_id, connection_accepted=connection_accepted
    )
    await seed_regression_conversation_from_mock(
        mod,
        url,
        prospect_id,
        connection_accepted=connection_accepted,
    )

    meta = REGRESSION_SPECS[case_id]
    rounds_spec: list[RoundSpec] = meta["rounds"]
    repeat_final: bool = meta["repeat_final"]

    max_rounds = len(rounds_spec) + (3 if repeat_final else 0)
    round_index = 0
    while round_index < max_rounds:
        if not repeat_final and round_index >= len(rounds_spec):
            pytest.fail(
                f"{case_id}: exhausted spec rounds ({len(rounds_spec)}) at loop {round_index}"
            )
        spec_idx = round_index if round_index < len(rounds_spec) else len(rounds_spec) - 1
        spec = rounds_spec[spec_idx]

        try:
            # Single-prospect mode is now the only mode the skill supports.
            invoke_claude_cli(
                f'Run conversation-planner skill for prospect_id="{prospect_id}".'
            )
        except Exception as exc:
            pytest.fail(f"[{spec['id']}] round={round_index} invoke_claude_cli: {exc}")
        session = _mock.get_session(url)
        if session is None:
            pytest.fail(
                f"[{spec['id']}] round={round_index}: no mock session for {url!r}"
            )
        allowed_stages = spec.get("allowed_stages")
        await assert_state_after_planner_round(
            mod, url, prospect_id, allowed_stages, session
        )
        await apply_regression_schedule_fallback(mod, url, prospect_id)
        await promote_connection_ended_from_conversation(mod, url, prospect_id)
        if spec.get("assert_meeting"):
            await assert_meeting_scheduled(mod, prospect_id, profile_url=url)
        await assert_connection_ended_when_conversation_terminal(
            mod, url, prospect_id
        )

        round_index += 1


def run_scenario(case_id: str) -> None:
    """Sync wrapper for :func:`run_scenario_async`."""
    asyncio.run(run_scenario_async(case_id))
