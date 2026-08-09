---
name: ebase
description: "LinkedIn recruiting outreach that runs inside Claude Code. Sends personalized connection requests, plans multi-step DM sequences, and replies to posts from your own signed-in Chrome session under LinkedIn's safe daily limits."
---

# ebase — LinkedIn Outreach for Claude Code

Outreach that won't get you flagged. ebase is a LinkedIn recruiting outreach system that runs entirely inside Claude Code, driving your own signed-in Chrome session via a purpose-built MCP server. Every action respects LinkedIn's safe daily limits (25 connection requests, 50 DMs, 100 profile views).

## Install

Requires macOS, Python 3.10+, Google Chrome, and Claude Code. Run this yourself in a terminal — it's not meant to be pasted into an agent as a set of instructions to execute.

```bash
git clone https://github.com/embeddingvc/ebase.git ~/ebase && cd ~/ebase
./install.sh
```

or, without cloning first:

```bash
curl -fsSL https://raw.githubusercontent.com/embeddingvc/ebase/main/install.sh | bash
```

`install.sh` is idempotent — re-run it any time as the repair path for a half-broken install. It bootstraps `uv`, runs `uv sync` + `playwright install chromium`, registers the LinkedIn MCP server (`claude mcp`), and syncs `outreach/skills/*` into `~/.claude/skills/`. It prints one `[install] [n/9] step…` line per phase; a `warn:`-prefixed line means something needs attention, and most already name their own fix (e.g. "uv sync failed... delete .venv and re-run").

Once it finishes: open the ebase Chrome window (`make browser` launches it if needed — it's an isolated profile at `~/.linkedin-chrome-profile`, separate from your everyday Chrome), sign in to LinkedIn, and confirm you see your feed. Then open Claude Code in `~/ebase` and run `/setup-outreach` to scrape your profile and build your persona/campaign config.

### Troubleshooting

Check CDP is up:

```bash
curl -sf http://localhost:9222/json/version && echo CDP_UP || echo CDP_DOWN
```

If `CDP_DOWN`:

- **Chrome isn't installed** — install it from google.com/chrome, re-run `./install.sh`.
- **Chrome was already running without the debug flag** — the most common cause. Launching a new Chrome process with `--remote-debugging-port` does nothing if Chrome is already running; the OS just focuses the existing window. Fully quit Chrome (Cmd+Q, not just close the window), then run `make browser`.
- **Port 9222 is held by something else** — `lsof -nP -iTCP:9222 -sTCP:LISTEN`. Free it, or retry on another port: `CDP_PORT=9223 make browser` (keep the port consistent — the MCP server needs to match).
- **Still down** — `bin/browser-service status` for the raw service state.

Verify the install landed:

```bash
claude mcp list 2>/dev/null | grep -q '^linkedin' && echo MCP_OK || echo MCP_MISSING
ls ~/.claude/skills 2>/dev/null | grep -qx setup-outreach && echo SKILLS_OK || echo SKILLS_MISSING
```

If either is missing, re-run `./install.sh` (registration is idempotent).

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

1. **Install** — run `install.sh` to register the LinkedIn MCP server and skills
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
