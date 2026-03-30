"""
Outreach worker — queue-draining server.

Reads jobs from outreach/queue/pending.json, executes each one using a
persistent LinkedInBrowser (attach mode), then writes the result to
outreach/queue/completed.json (success) or outreach/queue/failed.json.

The worker polls the queue file every POLL_INTERVAL seconds, so you can
add new jobs at runtime simply by editing pending.json (or appending via
the CLI helpers below).

Usage:
    # Normal start (attaches to Chrome on localhost:9222)
    uv run outreach/worker.py

    # Custom CDP URL or poll interval
    CDP_URL=http://localhost:9223 POLL_INTERVAL=10 uv run outreach/worker.py

The worker expects Chrome to already be running with --remote-debugging-port.
Start it with:
    make browser
or manually:
    open -a "Google Chrome" --args \\
      --remote-debugging-port=9222 \\
      --user-data-dir=$HOME/.linkedin-chrome-profile \\
      --no-first-run
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent
QUEUE_DIR  = BASE_DIR / "outreach" / "queue"
PENDING    = QUEUE_DIR / "pending.json"
COMPLETED  = QUEUE_DIR / "completed.json"
FAILED     = QUEUE_DIR / "failed.json"
PID_FILE   = BASE_DIR / "outreach" / "storage" / "worker.pid"

CDP_URL       = os.environ.get("CDP_URL", "http://localhost:9222")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "5"))

logger = logging.getLogger("linkedin.worker")


def _chrome_running(cdp_url: str = CDP_URL) -> bool:
    """Return True if Chrome is already listening on the CDP port."""
    try:
        urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2)
        return True
    except Exception:
        return False

# Make the project root importable when run directly.
sys.path.insert(0, str(BASE_DIR))

from outreach.browser import LinkedInBrowser  # noqa: E402
from outreach.planner import plan_message     # noqa: E402


# ── Queue helpers ─────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pop_next_job() -> dict | None:
    """
    Remove and return the highest-priority job that is ready to run.
    Returns None if the queue is empty or all jobs are deferred.
    """
    data = _load_json(PENDING, {"queue": []})
    queue = data.get("queue", [])

    now = datetime.now(timezone.utc).isoformat()
    ready = [
        j for j in queue
        if j.get("run_after") is None or j["run_after"] <= now
    ]
    if not ready:
        return None

    # Pick highest priority (lowest number wins), then oldest added_at.
    ready.sort(key=lambda j: (j.get("priority", 99), j.get("added_at", "")))
    job = ready[0]
    queue.remove(job)
    _save_json(PENDING, {"queue": queue})
    return job


def record_result(job: dict, success: bool, note: str = "") -> None:
    key  = "completed" if success else "failed"
    path = COMPLETED if success else FAILED
    data = _load_json(path, {key: []})
    data[key].append({
        **job,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "note":        note,
    })
    _save_json(path, data)


# ── Job handlers ──────────────────────────────────────────────────────────────

async def handle_send_connection_request(job: dict, li: LinkedInBrowser) -> str:
    prospect_file = BASE_DIR / "outreach" / "prospects" / f"{job['prospect_id']}.json"
    convo_file    = BASE_DIR / "outreach" / "conversations" / f"{job['prospect_id']}.json"

    with open(prospect_file) as f:
        prospect = json.load(f)
    with open(convo_file) as f:
        conversation = json.load(f)

    result  = plan_message(prospect, conversation)
    note    = result["message"]
    url     = prospect["linkedin_url"]

    sent = await li.send_connection_request(url, note=note)
    if not sent:
        raise RuntimeError("send_connection_request returned False")

    # Update conversation state.
    conversation["last_action"]           = "send_connection_request"
    conversation["last_action_timestamp"] = datetime.now(timezone.utc).isoformat()
    conversation["connection_note"]       = note
    conversation["next_action"]           = "send_followup_message"
    conversation["messages"].append({
        "sender":    "us",
        "text":      note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_json(convo_file, conversation)

    await li.screenshot(f"connection_request_{job['prospect_id']}")
    return f"Connection request sent. Note: {note[:60]}…"


async def handle_send_followup_message(job: dict, li: LinkedInBrowser) -> str:
    prospect_file = BASE_DIR / "outreach" / "prospects" / f"{job['prospect_id']}.json"
    convo_file    = BASE_DIR / "outreach" / "conversations" / f"{job['prospect_id']}.json"

    with open(prospect_file) as f:
        prospect = json.load(f)
    with open(convo_file) as f:
        conversation = json.load(f)

    result  = plan_message(prospect, conversation)
    message = result["message"]
    url     = prospect["linkedin_url"]

    sent = await li.send_message(url, message)
    if not sent:
        raise RuntimeError("send_message returned False")

    conversation["last_action"]           = "send_followup_message"
    conversation["last_action_timestamp"] = datetime.now(timezone.utc).isoformat()
    conversation["next_action"]           = "await_reply"
    conversation["messages"].append({
        "sender":    "us",
        "text":      message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_json(convo_file, conversation)

    await li.screenshot(f"followup_{job['prospect_id']}")
    return f"Follow-up sent. Message: {message[:60]}…"


async def handle_scrape_profile(job: dict, li: LinkedInBrowser) -> str:
    prospect_file = BASE_DIR / "outreach" / "prospects" / f"{job['prospect_id']}.json"
    with open(prospect_file) as f:
        prospect = json.load(f)

    scraped = await li.scrape_profile(prospect["linkedin_url"])

    # Merge scraped data into the prospect file.
    prospect.update({k: v for k, v in scraped.items() if v})
    _save_json(prospect_file, prospect)
    return f"Profile scraped: {scraped['name']!r}, {len(scraped.get('recent_posts', []))} posts"


# ── Dispatch ──────────────────────────────────────────────────────────────────

HANDLERS = {
    "send_connection_request": handle_send_connection_request,
    "send_followup_message":   handle_send_followup_message,
    "scrape_profile":          handle_scrape_profile,
}


async def execute_job(job: dict, li: LinkedInBrowser) -> None:
    action  = job.get("action", "")
    handler = HANDLERS.get(action)
    pid_str = job.get("prospect_id", "?")

    if not handler:
        raise ValueError(f"Unknown action: {action!r}")

    logger.info("Running job: %s → %s", action, pid_str)
    note = await handler(job, li)
    record_result(job, success=True, note=note)
    logger.info("✅  %s → %s  (%s)", action, pid_str, note)


# ── Main loop ─────────────────────────────────────────────────────────────────

_running = True


def _handle_sigterm(*_) -> None:
    global _running
    logger.warning("SIGTERM received — shutting down after current job.")
    _running = False


async def run_worker() -> None:
    global _running

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT,  _handle_sigterm)

    # Write PID so `make stop` can kill us.
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    logger.info("Started (pid=%d)  CDP=%s  poll=%ss", os.getpid(), CDP_URL, POLL_INTERVAL)
    logger.info("Queue:  %s", PENDING)
    logger.info("Press Ctrl-C to stop.")

    if not _chrome_running():
        logger.error(
            "Chrome not reachable at %s — run `make browser` first, then re-run `make server`.",
            CDP_URL,
        )
        PID_FILE.unlink(missing_ok=True)
        return

    async with LinkedInBrowser(mode="attach", cdp_url=CDP_URL) as li:
        await li.assert_logged_in()
        while _running:
            job = pop_next_job()

            if job is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            try:
                await execute_job(job, li)
            except Exception as exc:
                note = str(exc)
                record_result(job, success=False, note=note)
                logger.error("❌  %s → %s  (%s)", job.get("action"), job.get("prospect_id"), note)

            # Brief pause between jobs to avoid hammering LinkedIn.
            await asyncio.sleep(2)

    PID_FILE.unlink(missing_ok=True)
    logger.info("Stopped.")


if __name__ == "__main__":
    _log_dir = BASE_DIR / "logs"
    _log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=[
            logging.FileHandler(_log_dir / "worker.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    asyncio.run(run_worker())
