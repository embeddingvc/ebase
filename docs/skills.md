# Claude skills

Workflow instructions for Claude live in **`outreach/skills/`**. Each skill is its **own directory** with a **`SKILL.md`** file. Skills assume the **LinkedIn MCP server** is available — see [Manual install & Claude Desktop MCP setup](./install.md).

## Browser tool policy (applies to every skill)

Every LinkedIn browser action across these skills runs **only** through the LinkedIn MCP server (tools prefixed `mcp__linkedin__*`). Each `SKILL.md` opens with a **Browser tool policy** block that forbids substituting any other browser surface — including generic `chrome-devtools` / `playwright` / `puppeteer` / `browser-use` / `browserbase` / `gstack` browser MCPs, the **Claude in Chrome** extension, `WebFetch` / `WebSearch`, and `curl` / `wget` against `linkedin.com`. The LinkedIn MCP attaches to the operator's logged-in Chrome over CDP `9222` with the project's rate-limits and bot-detection safeguards; competing surfaces bypass those and put the operator's account at risk. If `mcp__linkedin__*` tools are not registered in the current Claude CLI session, the skill must stop and report — not silently fall back to another browser tool.

## Core skills (this repo)

- `setup-outreach` — interactive first-run wizard (see below)
- `conversation-planner` (single-prospect only; dispatched per row by the dashboard's per-prospect plan sweep)
- `sync-planner-persona-from-linkedin`
- `send-connection-request`
- `reply-to-post`

The former `sync-pending-connections` skill has been retired — the dashboard now runs that workload as a deterministic Python sweep (`web/connection_sync_sweep.py`) with no LLM in the loop. See [`docs/designs/per-connection-routines-with-backoff-design.md`](./designs/per-connection-routines-with-backoff-design.md).

## `setup-outreach` (first-run wizard)

Run **`/setup-outreach`** in Claude Code (or ask to “run setup-outreach”) after install. The skill walks through setup **one step at a time** and waits for your input before continuing.

**Profile setup loop** (the core of the wizard):

1. **`scrape_profile`** on `https://www.linkedin.com/in/me/` — draft `persona` + `organization` from name, headline, about, and recent posts
2. **Present** the draft in plain language and as JSON
3. **Refine** — you request corrections; the agent revises until you approve
4. **Sync** — **`merge_conversation_planner_identity`** writes `outreach/config/persona.json`

Optional later steps: campaign/tone tweaks via **`upsert_conversation_planner_config`**, then a readiness summary.

**Prerequisites:** Chrome with CDP (`make browser`), signed into LinkedIn in the installer Chrome profile, LinkedIn MCP registered. See [Quickstart](./quickstart.md) and [Conversation planner config](./conversation-planner.md).

For a deep LinkedIn-only identity refresh (experience, education, skills) without the wizard, use **`sync-planner-persona-from-linkedin`** instead (`parse_profile`-first).

## Install skills in Claude

1. `Customize` → `Skills` → `+` → `Create skill` → `Upload a skill`
2. Select the `SKILL.md` files under `outreach/skills/`
3. Repeat for `setup-outreach`, `conversation-planner`, `sync-planner-persona-from-linkedin`, `send-connection-request`, and `reply-to-post`

The one-command installer in the main [README](../README.md) (default mode) also copies these skills into `~/.claude/skills/<name>/` for you.
