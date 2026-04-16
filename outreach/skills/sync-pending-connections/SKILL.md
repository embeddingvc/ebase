---
name: sync-pending-connections
description: >
  Load connections.json via get_connections, find rows with connection_status pending,
  verify LinkedIn acceptance with is_first_degree_connection, and upsert each accepted
  row to connection_status connected using save_connection. Use when syncing invites,
  before batch conversation-planner runs, or when the user asks to refresh connection state.
---

# Sync Pending Connections

Reconcile **`outreach/connections.json`** with LinkedIn: anyone still marked **`pending`**
who is now a **1st-degree connection** on the live site gets updated to **`connected`**.

**Filesystem rule:** Do not read or write `outreach/` via workspace paths. Use MCP tools from
`tools/server.py`: **`get_connections`**, **`is_first_degree_connection`**, **`save_connection`**,
and optionally **`get_prospect`** / **`upsert_prospect`**, **`append_action_log`**.

**Test / fixtures:** Never read or edit `tests/` or `tests/fixtures/` for this flow.

## When to Use

- User asks to check pending connections, sync invites, or update who has accepted
- Before **`conversation-planner`** batch mode so `connection_status: "pending"` rows are not skipped incorrectly
- Periodic housekeeping after sending connection requests

## Prerequisites

- **Live mode:** Chrome attached (same as other LinkedIn tools); the operator must be logged in.
- **Mock mode:** `is_first_degree_connection` follows mock session rules (see `tools/mock.py`): a row
  stays pending until the mock session has recorded the invite or thread activity.

## Steps

### 1. Load the connections list

```
Tool: get_connections
```

- If the tool returns a string starting with `error:`, report it and stop.
- Parse the JSON. Expect top-level **`connections`** (array of objects).

### 2. Select pending rows

Filter to entries where **`connection_status`** is exactly **`"pending"`** (case-sensitive).

- If none: report `No pending connections.` and stop.

### 3. Check each on LinkedIn

For **each** pending row, in order:

1. Read **`profile_url`** (required). Skip with a warning if missing.
2. Call **`is_first_degree_connection`** with that `profile_url` (and `cdp_url` if the host uses a non-default CDP endpoint).
3. Parse the returned JSON: field **`first_degree`** (boolean).

### 4. Promote accepted invites

When **`first_degree`** is **`true`**:

1. Call **`save_connection`** with:
   - **`profile_url`** — same as the row
   - **`name`** — from the existing row; if empty, optionally call **`scrape_profile`** once for that URL and use the scraped `name`
   - **`title`** — from the existing row; if empty, optionally fill from **`scrape_profile`** (`title` / headline)
   - **`prospect_id`** — pass the row’s `prospect_id` if present so the id is preserved; otherwise omit and let `save_connection` derive it
   - **`note_sent`** — pass the row’s `note_sent` value if the field exists; use JSON `null` / omit only when the row had no note
   - **`connection_status`** — **`"connected"`** (must match `prospect.schema.json` enum: `none` | `pending` | `connected`)

2. **`save_connection`** refreshes **`connected_at`** to the current time — that timestamp represents *when this sync detected acceptance*, which is fine for bookkeeping.

When **`first_degree`** is **`false`**, leave the row unchanged and count it as still pending.

### 5. (Optional) Align prospect records

If the row has a **`prospect_id`** and **`get_prospect(prospect_id)`** succeeds:

- Set **`connection_status`** → **`"connected"`** on the prospect object if it was **`"pending"`**.
- Advance **`outreach_stage`** from **`"pending_connection"`** toward **`"engaged"`** (or your pipeline’s next stage) when appropriate.
- **`upsert_prospect(prospect_id, json.dumps(prospect))`**

### 6. (Optional) Action log

After each promotion (or once at the end with a list), **`append_action_log`**:

```json
{
  "action": "connection_accepted_sync",
  "prospect_id": "<id or null>",
  "profile_url": "<url>",
  "timestamp": "<ISO UTC>"
}
```

### 7. Report

Print a short summary:

```
── Pending connections sync ─────────────────────────────────
Checked:  <N> pending row(s)
Now connected:  <list of names + profile_url>
Still pending:  <N>  (names optional)
─────────────────────────────────────────────────────────────
```

## Notes

- **`is_first_degree_connection`** is the source of truth for “can DM without InMail”; do not infer acceptance from `scrape_profile` **`connection_degree`** alone on stale data.
- If LinkedIn rate-limits or the browser session is invalid, surface the error and stop or continue with remaining URLs per operator preference.
- Rows with **`connection_status`** already **`"connected"`** are ignored by this skill (not re-checked unless the user asks for a full audit).
