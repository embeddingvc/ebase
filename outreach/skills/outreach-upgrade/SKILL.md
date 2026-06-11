---
name: outreach-upgrade
description: >-
  Upgrade LinkedIn-Outreach to the latest version from git. Detects the repo
  checkout, runs git pull + uv sync + skill/MCP refresh, and shows what changed.
  Use when asked to upgrade, update, or get the latest outreach version; also
  invoked inline when other skills detect UPGRADE_AVAILABLE.
---

# Outreach Upgrade

Upgrade the LinkedIn-Outreach installation and refresh Claude skills + MCP.

Voice triggers: "upgrade outreach", "update linkedin outreach", "get latest version".

---

## Inline upgrade flow (referenced by setup-outreach, send-connection-request)

Run at the **start** of those skills (before any outreach work):

```bash
bin/outreach-update-check 2>/dev/null || true
```

Parse the **one-line** output:

| Output | Action |
|--------|--------|
| `UPGRADE_AVAILABLE <old> <new>` | Follow **Step 1** below (ask user or auto-upgrade) |
| `UPGRADED <old> <new>` | Log success, continue with the invoking skill |
| `JUST_UPGRADED <old> <new>` | Log success, continue with the invoking skill |
| `UP_TO_DATE <ver>` or empty | Continue silently |

Network or git failures produce no output — **do not block** the invoking skill.

### Step 1: Ask the user (or auto-upgrade)

```bash
_AUTO=""
[ "${OUTREACH_AUTO_UPGRADE:-}" = "1" ] && _AUTO="true"
[ -z "$_AUTO" ] && _AUTO=$(bin/outreach-config get auto_upgrade 2>/dev/null || true)
echo "AUTO_UPGRADE=$_AUTO"
```

**If `AUTO_UPGRADE=true` or `AUTO_UPGRADE=1`:** Skip AskQuestion. Log
"Auto-upgrading LinkedIn-Outreach v{old} → v{new}…" and run **Step 2**.

**Otherwise**, use **`AskQuestion`**:

- Question: "LinkedIn-Outreach **v{new}** is available (you're on v{old}). Upgrade now?"
- Options:
  - **Yes, upgrade now**
  - **Always keep me up to date**
  - **Not now**
  - **Never ask again**

| Choice | Action |
|--------|--------|
| Yes, upgrade now | **Step 2** |
| Always keep me up to date | `bin/outreach-config set auto_upgrade true` → tell user auto-upgrade is on → **Step 2** |
| Not now | Write snooze (see below) → continue invoking skill |
| Never ask again | `bin/outreach-config set update_check false` → continue invoking skill |

**Snooze ("Not now")** — escalating backoff for the same remote version:

```bash
_SNOOZE_FILE="$HOME/.linkedin-outreach/update-snoozed"
_REMOTE_VER="{new}"
_CUR_LEVEL=0
if [ -f "$_SNOOZE_FILE" ]; then
  _SNOOZED_VER=$(awk '{print $1}' "$_SNOOZE_FILE")
  if [ "$_SNOOZED_VER" = "$_REMOTE_VER" ]; then
    _CUR_LEVEL=$(awk '{print $2}' "$_SNOOZE_FILE")
    case "$_CUR_LEVEL" in *[!0-9]*) _CUR_LEVEL=0 ;; esac
  fi
fi
_NEW_LEVEL=$((_CUR_LEVEL + 1))
[ "$_NEW_LEVEL" -gt 3 ] && _NEW_LEVEL=3
echo "$_REMOTE_VER $_NEW_LEVEL $(date +%s)" > "$_SNOOZE_FILE"
```

Tell the user: next reminder in 24h (level 1), 48h (level 2), or 1 week (level 3+).
Tip: `bin/outreach-config set auto_upgrade true` for silent upgrades.

### Step 2: Run upgrade

```bash
bin/outreach-update-check --apply 2>/dev/null || bin/outreach-upgrade "{old}" "{new}"
```

On success, parse `UPGRADED <old> <new>` and show:

```
LinkedIn-Outreach v{new} — upgraded from v{old}!

Run `git log v{old}..v{new} --oneline` in the repo for details, or see CHANGELOG if present.
```

On failure, warn the user and continue with the invoking skill (do not abort outreach).

### Step 3: Continue

Resume the skill the user originally invoked (setup-outreach, send-connection-request, etc.).

---

## Standalone usage (`/outreach-upgrade`)

1. Force a fresh check:
   ```bash
   bin/outreach-update-check --force 2>/dev/null || true
   ```
2. If `UPGRADE_AVAILABLE <old> <new>`: follow Steps 1–2.
3. If no output: tell the user they're on the latest version (read `VERSION` in the repo root).

---

## Config (`~/.linkedin-outreach/config`)

| Key | Default | Meaning |
|-----|---------|---------|
| `auto_upgrade` | `false` | Skip prompts; upgrade when an update is detected |
| `update_check` | `true` | Run version check at skill start |
| `install_local` | `false` | On upgrade, sync skills to `~/.claude/skills` (set `true` for local-only MCP) |

```bash
bin/outreach-config set auto_upgrade true
bin/outreach-config set update_check false
bin/outreach-config set install_local true
```
