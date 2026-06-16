---
name: ebase
description: >-
  LinkedIn recruiting outreach that runs inside Claude Code. Sends personalized
  connection requests, plans multi-step DM sequences, syncs thread state from
  LinkedIn, and replies to posts — all from your own signed-in Chrome session
  under LinkedIn's safe daily limits. Includes 7 skills: setup-outreach,
  send-connection-request, conversation-planner, sync-planner-persona-from-linkedin,
  reply-to-post, outreach-upgrade, and outreach-uninstall.
---

# ebase — LinkedIn Outreach for Claude Code

Outreach that won't get you flagged. ebase is a LinkedIn recruiting outreach system that runs entirely inside Claude Code, driving your own signed-in Chrome session via a purpose-built MCP server. Every action respects LinkedIn's safe daily limits (25 connection requests, 50 DMs, 100 profile views).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/embeddingvc/ebase/main/install.sh | bash
```

Then run `/setup-outreach` in Claude Code to configure your operator profile.

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

1. **Install** — one curl command registers the LinkedIn MCP server and skills with Claude Code
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
