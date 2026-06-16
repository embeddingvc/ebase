# Quickstart (live browser automation)

Day-to-day, the simplest flow is:

```bash
make run
```

That will:

- Start Chrome (if not already running) with a dedicated profile and CDP port.
- Start the worker in the foreground (`make server`).

Then log into LinkedIn in the Chrome window (first time per profile) and use either:

- **Claude CLI** (recommended for installation)
  - `make claude-install` — default: `--scope user` MCP + sync skills to `~/.claude/skills`
  - `make claude-install LOCAL=1` — `--scope local` MCP only; skills stay under `outreach/skills/` in the repo
- **Claude + MCP tools**
- **Queue files + worker** (recommended for batch automation)

## Live mode checklist

1. Start Chrome with debugging (from the repo root):

   ```bash
   make browser
   ```

2. Sign in to LinkedIn in that Chrome window.

3. Use Claude with the MCP tools as usual.

If Chrome is not running with remote debugging, live tools will fail until `make browser` (or an equivalent launch) is used.

## First-run profile setup

Before sending outreach, configure who the planner speaks as:

1. In Claude Code, run **`/setup-outreach`** (or ask to “run setup-outreach”).
2. The skill checks your browser session, **`scrape_profile`**s your signed-in LinkedIn profile, and drafts `persona` + `organization`.
3. Review the draft, request edits, then approve — the skill persists via **`merge_conversation_planner_identity`** to `outreach/config/persona.json`.
4. Optionally tune campaign goal/topic in the same wizard.

See [Claude skills — setup-outreach](./skills.md#setup-outreach-first-run-wizard) and [Conversation planner config](./conversation-planner.md).

## Example usage

0. **`/setup-outreach`** — configure operator profile (recommended first step).
1. Connect to `<linkedin-url>`.
2. Is `<linkedin-url>` my connection?
3. Add `Run conversation planner skill` as a scheduled task.

## Mock mode (optional, no browser)

The core MCP server (`tools/server.py`) is live-only. For scripted tests without a browser, use the mock-capable MCP server and fixtures under [`testing/`](../testing/README.md): set `OUTREACH_MOCK=1` and register `testing/tools/server.py` instead. See `testing/README.md` for the dev dashboard and regression suite.
