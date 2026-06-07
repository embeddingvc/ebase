# Claude skills

Workflow instructions for Claude live in **`outreach/skills/`**. Each skill is its **own directory** with a **`SKILL.md`** file. Skills assume the **LinkedIn MCP server** is available — see [Manual install & Claude Desktop MCP setup](./install.md).

## Core skills (this repo)

- `setup-outreach` — interactive first-run wizard (browser, persona, campaign, smoke test)
- `conversation-planner` (single-prospect only; dispatched per row by the dashboard's per-prospect plan sweep)
- `sync-planner-persona-from-linkedin`
- `send-connection-request`
- `reply-to-post`

The former `sync-pending-connections` skill has been retired — the dashboard now runs that workload as a deterministic Python sweep (`web/connection_sync_sweep.py`) with no LLM in the loop. See [`docs/designs/per-connection-routines-with-backoff-design.md`](./designs/per-connection-routines-with-backoff-design.md).

## Install skills in Claude

1. `Customize` → `Skills` → `+` → `Create skill` → `Upload a skill`
2. Select the `SKILL.md` files under `outreach/skills/`
3. Repeat for `setup-outreach`, `conversation-planner`, `sync-planner-persona-from-linkedin`, `send-connection-request`, and `reply-to-post`

The one-command installer in the main [README](../README.md) (default mode) also copies these skills into `~/.claude/skills/<name>/` for you.
