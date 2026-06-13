---
name: outreach-uninstall
description: >-
  Remove LinkedIn-Outreach from Claude Code: stop dashboard/worker, unregister
  MCP, clean permissions, optionally delete synced skills and local outreach
  data. Use when the user asks to uninstall, remove, or tear down outreach.
---

# Outreach Uninstall

Remove LinkedIn-Outreach integration from Claude Code and optionally delete
local outreach data. **Does not delete the git checkout** — the repo stays on
disk for re-install.

Voice triggers: "uninstall outreach", "remove linkedin outreach", "tear down outreach".

---

## Before you start

Explain what will be removed and confirm scope with **`AskQuestion`** (or chat):

| Option | What happens |
|--------|----------------|
| **Core only** | Stop services + MCP + permissions + `~/.claude/skills/` outreach copies |
| **Core + data** | Above + repo `outreach/` runtime files (connections, conversations, persona, logs) |
| **Full cleanup** | Above + `~/.linkedin-outreach/` + dedicated Chrome profile |

Default recommendation: **Core only** — keeps outreach history and persona for a future re-install.

---

## Step 1 — Run the uninstall script

From the repo root (never guess paths — resolve the workspace root first):

**Interactive (preferred):**

```bash
./uninstall.sh
```

The script asks **yes/no** before each category. The user can decline any step.

**Non-interactive** (only after explicit user confirmation of scope):

```bash
# Core: MCP, permissions, skills, stop services
./uninstall.sh -y

# Core + repo outreach data + state dir
./uninstall.sh -y --remove-data --remove-state

# MCP only (leave skills and data)
./uninstall.sh -y --mcp-only
```

| Flag | Effect |
|------|--------|
| `-y` / `--yes` | Skip prompts for steps the flags already selected |
| `--mcp-only` | MCP + permissions only |
| `--no-skills` | Keep `~/.claude/skills/<outreach-skill>/` |
| `--remove-data` | Delete repo runtime outreach files |
| `--remove-state` | Delete `~/.linkedin-outreach/` |
| `--remove-chrome-profile` | Delete `~/.linkedin-chrome-profile/` |

Do **not** pass `--remove-data` or `--remove-chrome-profile` unless the user
explicitly opted into that scope.

---

## Step 2 — Verify

After the script finishes, confirm:

1. `claude mcp list` — no `linkedin` server (if `claude` is on PATH).
2. Skills gone from `~/.claude/skills/` (if user chose skill removal):
   - `setup-outreach`, `send-connection-request`, `conversation-planner`, etc.

Summarize the script's ✓ / ○ lines for the user.

---

## Step 3 — Re-install pointer

If they want outreach again later:

```bash
./install.sh
# or: make claude-install
```

---

## What is never deleted automatically

- The **git repository** / source tree
- **`.venv`** / Python environment (run `rm -rf .venv` manually if desired)
- **`.env`** (operator email / SMTP — contains secrets; user must delete manually)
- Outreach data — unless `--remove-data` or the user confirmed data deletion

---

## Troubleshooting

| Symptom | Guidance |
|---------|----------|
| `claude` not found | MCP removal skipped — install Claude Code or remove MCP entries manually from `~/.claude.json` |
| Non-interactive failure | Re-run with `-y` after user confirms scope |
| Skills still in home dir | User declined removal or used `--no-skills`; remove manually or re-run |
| Chrome still signed in | Profile kept unless `--remove-chrome-profile` |
