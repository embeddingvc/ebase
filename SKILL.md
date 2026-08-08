---
name: ebase
description: "LinkedIn recruiting outreach that runs inside Claude Code. Sends personalized connection requests, plans multi-step DM sequences, and replies to posts from your own signed-in Chrome session under LinkedIn's safe daily limits."
---

# ebase — LinkedIn Outreach for Claude Code

Outreach that won't get you flagged. ebase is a LinkedIn recruiting outreach system that runs entirely inside Claude Code, driving your own signed-in Chrome session via a purpose-built MCP server. Every action respects LinkedIn's safe daily limits (25 connection requests, 50 DMs, 100 profile views).

## Install (agent-run)

**If you (the agent) were just handed this file** — e.g. the user pasted `set up https://ebase.dev/SKILL.md` — you are reading raw text over WebFetch, not a registered skill. Run the steps below yourself with your Bash tool, narrating each one in a sentence or two before you run it. Don't dump raw script output; summarize pass/fail and move on. Stop and ask the user only at the points marked **ask**.

This is safe to run more than once — every step is idempotent, so re-pasting this file is also the repair path for a half-broken install.

**0. Locate or clone the repo.**

```bash
[ -f pyproject.toml ] && grep -q 'name = "ebase"' pyproject.toml && echo IN_REPO || echo NOT_IN_REPO
```

If `NOT_IN_REPO`: clone it (`git clone https://github.com/embeddingvc/ebase.git ~/ebase`) if `~/ebase` doesn't exist yet, or `git -C ~/ebase pull --ff-only` if it does, then `cd ~/ebase` for every step below. If `git pull --ff-only` fails (local edits or diverged branch), stop and **ask** how to proceed rather than discarding anything.

**1. Prerequisite check.** Confirm `curl`, `git`, and macOS/Linux before continuing — `require_cmd`-style, fail fast with the exact missing tool named. Chrome and `uv` are handled by step 2, not required up front.

**2 & 3. Deps, MCP, and skill registration — delegate to `install.sh`.** This script already implements prereqs, `uv` bootstrap, `uv sync` + `playwright install chromium`, idempotent `claude mcp` registration, and an idempotent `rsync --delete` sync of `outreach/skills/*` into `~/.claude/skills/`. Don't re-implement any of that in bash yourself — run it and read its output:

```bash
./install.sh --skip-linkedin-login
```

(`--skip-linkedin-login` skips the script's own blocking "press Enter" prompt — you drive the LinkedIn sign-in conversationally in step 4 instead.) It prints one `[install] [n/9] step…` line per phase and a `warn:`-prefixed line on anything that needs attention. Read the whole log; most failures already carry their own fix (e.g. "uv sync failed... delete .venv and re-run") — apply it and re-run once before troubling the user. If it exits non-zero on `uv sync` or `playwright install`, that's almost always a network or disk-space problem outside your control — report the exact `warn:` line and **ask** how to proceed rather than guessing.

**4. Chrome / CDP verification — this is the step that most often needs a real conversation, so don't just trust `install.sh`'s own (non-fatal) warning and move on.**

```bash
curl -sf http://localhost:9222/json/version && echo CDP_UP || echo CDP_DOWN
```

If `CDP_UP`: done, continue to step 5.

If `CDP_DOWN`, work through these in order — each is a distinct real-world cause, don't just retry blindly:

- **Chrome isn't installed.** `install.sh` already said so (`Google Chrome not found`). **Ask** the user to install it from google.com/chrome, then re-run `./install.sh --skip-linkedin-login`.
- **A Chrome instance is already running without the debug flag.** The most common cause: launching a *new* Chrome process with `--remote-debugging-port` does nothing if Chrome is already running, because the OS just focuses the existing instance. Check `pgrep -f "Google Chrome"`; if it's running, **ask** the user to fully quit Chrome (Cmd+Q, not just close the window), then run `make browser` (or re-run `./install.sh --skip-linkedin-login`) and re-check `CDP_UP`.
- **Port 9222 is held by something else.** `lsof -nP -iTCP:9222 -sTCP:LISTEN`. If it's not Chrome, either stop that process or retry with a different port: `CDP_PORT=9223 make browser` (note the port for step 5/6 — the MCP server needs to match).
- **Multiple Chrome profiles.** ebase always launches its own isolated profile at `~/.linkedin-chrome-profile` — it never touches your everyday Chrome profile/history. If the user is confused about "which Chrome window", point them at that profile specifically, not "Chrome" in general.
- **Still down after the above:** `bin/browser-service status` for the raw service state, then **ask** rather than looping indefinitely.

Once `CDP_UP`, confirm LinkedIn sign-in conversationally rather than assuming: **ask** the user to open the ebase Chrome window, sign in to LinkedIn (or confirm they already are — this is *their* real signed-in session, it stays signed in across installs), and confirm they see their feed, not a login page. Nothing on LinkedIn is touched until they do this.

**5. Verify the install actually landed** before declaring success:

```bash
claude mcp list 2>/dev/null | grep -q '^linkedin' && echo MCP_OK || echo MCP_MISSING
ls ~/.claude/skills 2>/dev/null | grep -qx setup-outreach && echo SKILLS_OK || echo SKILLS_MISSING
```

If either is missing, re-run `./install.sh --skip-linkedin-login` once (registration is idempotent — safe to repeat) before escalating to the user.

**6. Mandatory tail: hand off to `/setup-outreach`.** Don't stop at "installed" — the first session should end at a **read-only win**: LinkedIn profile scraped, persona drafted and shown back for edit, pipeline initialized. Nothing is sent and nothing is regrettable. Immediately continue into the `setup-outreach` skill (now registered in `~/.claude/skills/setup-outreach/`) and follow it step by step as documented there — do not run it as one uninterrupted block; it has its own "stop and wait for the user" pacing.

**Fallback (no agent, plain terminal):**

```bash
curl -fsSL https://raw.githubusercontent.com/embeddingvc/ebase/main/install.sh | bash
```

then run `/setup-outreach` in Claude Code by hand. This is the same `install.sh` step 2/3 above runs for you — use it if you're not pasting this file into an agent at all.

**Requirements:** macOS, Python 3.10+, Claude Code

## Included Skills

| Skill | Command | Description |
|-------|---------|-------------|
| **setup-outreach** | `/setup-outreach` | Interactive setup wizard — scrapes your LinkedIn profile, builds your persona and tone config, configures campaign settings |
| **send-connection-request** | `/send-connection-request` | Send a LinkedIn connection request with optional personalized note grounded in your campaign config |
| **conversation-planner** | `/conversation-planner` | Single-prospect DM sequencer — syncs the live thread, plans the next message in a 5-step sequence, delivers via MCP |
| **sync-planner-persona-from-linkedin** | `/sync-planner-persona-from-linkedin` | Refresh operator identity in persona.json from LinkedIn using structured profile crawl |
| **reply-to-post** | `/reply-to-post` | Leave a comment on a LinkedIn post in your configured voice |
| **outreach-upgrade** | `/outreach-upgrade` | Upgrade ebase to the latest version from git with skill and MCP refresh |
| **outreach-uninstall** | `/outreach-uninstall` | Remove ebase from Claude Code — stops services, unregisters MCP, cleans permissions |

## When to Use

- You are a recruiter or talent partner doing LinkedIn outreach daily
- You want to replace tools like Dripify, Expandi, or Linked Helper with something that won't get your account restricted
- You want Claude to handle the research-connect-message pipeline while you focus on candidate conversations
- You need personalized, multi-touch outreach sequences that sound like you wrote them

## How It Works

1. **Install** — paste this file's URL into Claude Code (or run the curl fallback) to register the LinkedIn MCP server and skills
2. **Sign in to Chrome** — ebase drives your real authenticated Chrome session over CDP, not a headless bot
3. **Setup** — `/setup-outreach` scrapes your LinkedIn profile to build your operator persona and campaign config
4. **Outreach** — ask Claude to connect, follow up, or engage in natural language. Each action runs as a skill with structured MCP calls
5. **Automation** — a cron scheduler syncs connection accepts, plans follow-ups, and drives conversations toward meetings unattended

## Architecture

- **LinkedIn MCP server** — 30+ Playwright-backed tools for structured LinkedIn operations (scrape, connect, message, engage)
- **Claude skills** — 7 chainable workflows covering the full outreach lifecycle
- **Cron scheduler** — unattended routine sweeps for connection sync and conversation planning
- **Per-user state** — isolated prospects, conversations, and action logs in JSON/JSONL

## Rules

- NEVER exceed LinkedIn's daily action limits
- ALWAYS use the LinkedIn MCP server (`mcp__linkedin__*`) for browser actions — no other browser tools
- NEVER read or write `outreach/` data files directly — use the MCP filesystem tools
- NEVER send two sequence steps in a single run
- ALWAYS respect `prefers-reduced-motion` and operator-configured tone/style
