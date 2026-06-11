---
name: send-connection-request
description: Send a LinkedIn connection request (with an optional personalised note) via the MCP send_connection_request tool, then persist pipeline state with save_connection, upsert_conversation, append_action_log, and remove_pending_queue_entry — never raw outreach/ paths. Notes are grounded in the runtime planner campaign (campaign.topic / campaign.goal / persona) with per-prospect and per-invocation overrides. Use when the user asks to connect with, invite, or add a LinkedIn profile.
---

# Send Connection Request

## Update check (run first)

Before connecting, check for a newer LinkedIn-Outreach version:

```bash
bin/outreach-update-check 2>/dev/null || true
```

If output is `UPGRADE_AVAILABLE <old> <new>`, follow the inline flow in skill
**`outreach-upgrade`** (ask to upgrade). On
`UPGRADED`, `JUST_UPGRADED`, `UP_TO_DATE`, or empty output, continue below.
Do not block on network failures.

Scrape a LinkedIn profile, then immediately send a connection request — no confirmation step needed.
When you auto-generate a note, anchor it to the active campaign topic from the runtime planner
config (`get_conversation_planner_config` → `campaign.topic` / `campaign.goal` /
`campaign.value_proposition`), with per-prospect and per-invocation overrides described under
**Inputs → Topic precedence**.

**Filesystem rule:** Do not read or write `outreach/` files via workspace paths. Use MCP tools from
`tools/server.py`: **`get_conversation_planner_config`**, **`save_connection`**, **`get_conversation`**,
**`upsert_conversation`**, **`upsert_prospect`**, **`append_action_log`**, **`remove_pending_queue_entry`**.

**Test / fixtures:** Never read, edit, or overwrite `tests/fixtures/` or other `tests/` files during
connection flows. Do not seed MCP upserts from fixture JSON unless the user is explicitly maintaining tests.

## When to Use

- User asks to connect with, invite, or add a LinkedIn profile
- First step in an outreach sequence for a 2nd or 3rd-degree prospect
- Prospect file exists and `next_action` is `"send_connection_request"`

## Inputs

- `profile_url` (required) — full LinkedIn profile URL, e.g. `https://www.linkedin.com/in/username/`
- `note` (optional) — personalised connection note (LinkedIn limit: **300 chars**). Pass to send verbatim; omit to auto-generate from planner config + profile.
- `outreach_topic` (optional, per-invocation) — the angle for *this* connection note. Parse it from the user's natural-language ask. Examples:
  - `connect to <url> for AI startup ideas` → `outreach_topic = "AI startup ideas"`
  - `connect to <url> about catching up after grad school` → `outreach_topic = "catching up after grad school"`
  - `connect to <url>` (no qualifier) → fall through the precedence below.

### Topic precedence (highest → lowest)

When composing an auto-generated note, resolve `outreach_topic` in this order and stop at the first match:

1. **Per-invocation topic** parsed from the user's request (`for …`, `about …`, `re: …`, etc.).
2. **`prospect.outreach_topic`** from the prospect JSON.
3. **`campaign.topic`** from **`get_conversation_planner_config`** (the project-wide default for the active outreach setup).

If you resolved at level 1 (and the prospect did not already have the same topic), call **`upsert_prospect`** with the merged `outreach_topic` so later `conversation-planner` runs stay anchored on the same angle.

Skip topic resolution entirely when the user supplied `note` verbatim — that text is shipped as-is.

**Prospect JSON** (via `upsert_prospect` before you generate the note) also drives:

- `end_goal` — **`schedule_meeting`** (default when omitted): steer toward a short intro call or meeting. **`obtain_resume`**: recruiting path toward sharing a resume or profile artifact (maps from legacy `target_action: request_resume`). **`none`**: warm connect only — no meeting, resume, or scheduling ask in generated copy (e.g. old friend).

## Steps

### 1. Scrape the profile

Call the `scrape_profile` MCP tool first to fetch the prospect's details:

```
Tool: scrape_profile
  profile_url: <the LinkedIn URL>
```

Use the scraped data to:
- Check `connection_degree` — if it is `1`, abort and report: `"<Name> is already a 1st-degree connection. Use send_message to reach them directly."`
- Personalise the note (if one is being generated) using `name`, `title`, `about`, and `recent_posts`.

### 2. Compose the note (skip if `note` was passed verbatim)

If the user supplied a `note`, use it verbatim (trim silently to 300 chars if needed) and jump to Step 3.

Otherwise, load runtime planner config so the note is grounded in the active campaign — not a generic "let's connect":

```
Tool: get_conversation_planner_config
```

Use these fields when composing:

- `persona.name`, `persona.role`, `persona.organization` — who is sending the request.
- `organization.description` — one-line framing of the operator's org.
- `campaign.goal`, `campaign.topic`, `campaign.value_proposition` — what to invite them to explore. **`campaign.topic` is the default outreach topic** when neither the user nor the prospect supplied an override (see **Topic precedence** above).
- `message_rules.connection_note_char_limit` — soft cap (typically 200). The LinkedIn hard limit is **300**. Use the smaller of the two as your character budget.
- `message_rules.banned_phrases` and `message_rules.tone` — phrasing constraints to honor.

Then compose so that:

- The **resolved topic** is the angle of the note (not a generic invitation).
- It references at least one concrete signal from the scrape (`recent_posts`, `title`, mutual connection, or operator-supplied context like "we met at NeurIPS").
- It includes the prospect's first name.
- It honors `end_goal` — no meeting/resume ask if `end_goal == "none"`; light tee-up for a call if `schedule_meeting`; profile/resume angle if `obtain_resume`.
- It stays within the character budget — count carefully and trim before sending.

If the per-invocation topic came from the user's phrase (precedence level 1), call **`upsert_prospect`** to persist it onto the prospect record before sending. This keeps follow-ups in `conversation-planner` aligned on the same angle.

### 3. Send the connection request

Call `send_connection_request` immediately — no need to ask for confirmation:

```
Tool: send_connection_request
  profile_url: <the LinkedIn URL>
  note:        <note text, or omit for no note>
```

If a note is provided, verify it is ≤ 300 characters before calling the tool. Trim silently if needed.

The tool attaches to the running Chrome session, navigates to the profile, clicks the Connect button (or opens the More menu if Connect is hidden), optionally adds the note, and submits the invitation.

### 4. Handle the response

| Response | Meaning                                    | Action                                              |
|----------|--------------------------------------------|-----------------------------------------------------|
| `"ok"`   | Request sent successfully                  | Print confirmation (see below)                       |
| anything else | Send failed (already connected, pending, button not found, etc.) | Report the error; do NOT retry automatically |

### 5. Print confirmation

On success:

```
── Connection Request Sent ───────────────────────────────────
To:       <Name> (<profile_url>)
Title:    <title from scrape>
Sent at:  <current ISO timestamp>
Note:     "<note text>" (or "(none)")
─────────────────────────────────────────────────────────────
```

### 6. Update conversation state (if using outreach pipeline)

When you have a `prospect_id` for the pipeline:

1. **`get_conversation(prospect_id)`** — if the tool returns JSON text, parse it into `conversation`.
   If it returns `error: conversation not found`, build a minimal valid `conversation` object (schema:
   `prospect_id`, `outreach_stage`, `messages: []`, etc.) in memory.
2. Append to `conversation.messages` (conversation schema — no extra keys):
   `{ "sender": "operator", "text": "<note text or brief system line>", "timestamp": "<ISO UTC>", "sequence_step": 1 }`.
   Use the real note when one was sent; if none, use a short line such as `(connection request sent, no note)`.
3. Set `last_action` → `"send_connection_request"`, `last_action_timestamp` → now,
   `next_action` → `null`, and advance `outreach_stage` / `stage_history` per your pipeline (e.g.
   toward `pending_connection`). Snapshot **`end_goal`** (resolved: default `schedule_meeting` unless
   the prospect sets `end_goal` or legacy `target_action`) and **`outreach_topic`** (the **resolved**
   topic actually used for the note — per-invocation override → `prospect.outreach_topic` →
   `campaign.topic` from planner config) onto the conversation so later steps know what angle was
   used at connect time. If the resolved topic came from precedence level 3 (`campaign.topic`
   fallback), still snapshot it explicitly rather than leaving the field null.
4. **`upsert_conversation(prospect_id, json.dumps(conversation))`**
5. **`append_action_log(entry=json.dumps({...}))`**:
```json
{ "action": "connection_request_sent", "prospect_id": "<id>", "timestamp": "<ISO>", "note_char_count": <n>, "outreach_topic": "<resolved topic>" }
```
6. If you use the pending queue: **`remove_pending_queue_entry(prospect_id)`**

### 7. Update the connections list (MCP)

Call **`save_connection`** with:

| Parameter | Value |
|-----------|--------|
| `profile_url` | same LinkedIn URL |
| `name` | from scrape |
| `title` | from scrape (headline) |
| `prospect_id` | pipeline id if you already have one; if omitted, **`save_connection` fills it** from the LinkedIn URL slug (so the per-prospect conversation-planner dispatch can resolve the prospect later) |
| `note_sent` | note text, or `null` if sent without a note |
| `connection_status` | `"pending"` |

`save_connection` upserts by `profile_url` inside the project’s `connections.json` — do **not** edit
that file manually.

## Examples

### A. Per-invocation topic override

**User:** `Connect to https://www.linkedin.com/in/alexchen/ for AI startup ideas`

Parsed: `outreach_topic = "AI startup ideas"` (precedence level 1 — overrides `prospect.outreach_topic` and `campaign.topic`).

```
Tool call → scrape_profile(profile_url="https://www.linkedin.com/in/alexchen/")
→ { name: "Alex Chen", title: "ML Engineer at Acme", connection_degree: 2, recent_posts: [...] }

Tool call → get_conversation_planner_config()
→ { persona: { name: "Nova", organization: "Acme Capital" }, campaign: { topic: "AI startup opportunities and career exploration", ... }, message_rules: { connection_note_char_limit: 200, ... } }

# Topic resolves to "AI startup ideas" (user-supplied) — not campaign.topic.
# Persist to prospect so follow-ups stay aligned:
Tool call → upsert_prospect(prospect_id="alex_chen", prospect=json.dumps({ ..., "outreach_topic": "AI startup ideas" }))

Tool call → send_connection_request(
  profile_url="https://www.linkedin.com/in/alexchen/",
  note="Hi Alex — your post on retrieval evals stood out. I'm Nova at Acme Capital, mostly trading AI startup ideas with folks who've shipped infra at scale. Open to comparing notes?"
)

── Connection Request Sent ───────────────────────────────────
To:       Alex Chen (https://www.linkedin.com/in/alexchen/)
Title:    ML Engineer at Acme
Sent at:  2026-04-03T14:10:00+00:00
Topic:    "AI startup ideas" (per-invocation override)
Note:     "Hi Alex — your post on retrieval evals stood out…"
─────────────────────────────────────────────────────────────
```

### B. No topic supplied — fall back to campaign default

**User:** `Connect with https://www.linkedin.com/in/priya/`

Parsed: no per-invocation topic; prospect has no `outreach_topic`. Falls back to `campaign.topic` from `get_conversation_planner_config` (e.g. `"AI startup opportunities and career exploration"`). The note is composed around that angle and `outreach_topic` is **not** written back to the prospect (it's the project-wide default).

### C. Verbatim note (no auto-generation)

**User:** `Connect with https://www.linkedin.com/in/alexchen/ and say we met at NeurIPS`

The user supplied note text — skip planner config + topic resolution, send verbatim:

```
Tool call → send_connection_request(
  profile_url="https://www.linkedin.com/in/alexchen/",
  note="Hi Alex — great meeting you at NeurIPS! Would love to stay connected."
)
```

## Error Handling

- **Already a 1st-degree connection** — detected via scrape; do not call the tool. Report: `"<Name> is already a 1st-degree connection. Use send_message to reach them directly."`
- **Note too long** — trim to 300 chars before calling the tool.
- **Connect button not found** — tool returns an error string. Possible causes: pending request already sent, profile set to followers-only, or InMail-only. Report the raw error and suggest checking the profile manually.
- **Chrome not running** — CDP connection fails. Report: `"Could not connect to Chrome. Make sure Chrome is running with --remote-debugging-port=9222."`
- **Not logged in** — tool raises an error. Report: `"Not logged in to LinkedIn. Log in manually in the Chrome window and retry."`
- **Bot detection** — if the action fails with a timeout or unexpected redirect, stop immediately and report: `"LinkedIn may have triggered bot detection. Wait a few minutes before retrying."`
- **Daily limit** — LinkedIn imposes weekly invitation limits (~100–200). If errors appear after several sends in a session, pause and report: `"You may have hit LinkedIn's weekly invitation limit. Check your My Network page."`