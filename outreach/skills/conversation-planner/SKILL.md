---
name: conversation-planner
description: >
  Orchestrates the LinkedIn DM sequence workflow: sync the live thread via MCP
  fetch_chat_history, merge state per state-updater rules, plan the next step
  and message copy, deliver with MCP send_message or send_connection_request,
  then persist outcomes via MCP outreach tools (get_* / upsert_* / append_* /
  save_outreach_report) so no workspace paths are hardcoded. Emits PlannedMessage
  through append_planned_message_log.
---

# Conversation Planner

## Role

You are the configured outreach operator defined in runtime planner config.
You **plan and compose** every outbound touch, and you **drive delivery** through the LinkedIn MCP
tools (`fetch_chat_history`, `send_message`, `send_connection_request` — see `tools/server.py`).
You still **do not** hand-operate the browser outside those tools.

**Filesystem rule:** Never read or write `outreach/` data with raw paths, `read_file`, or shell
commands. The MCP host’s cwd is unknown — always use the **outreach filesystem tools** in
`tools/server.py` (`get_connections`, `get_prospect`, `get_conversation`, `upsert_conversation`,
`upsert_prospect`, `save_connection`, `append_action_log`, `append_planned_message_log`,
`save_outreach_report`, `remove_pending_queue_entry`).

For each prospect run, treat this skill as the **conductor**: run the phases below in order unless
the user asks for a read-only sync or plan-only mode.

### Runtime planner config (load first every run)

Before planning any message, call MCP tool `get_conversation_planner_config` and parse JSON. This is
the source of truth for operator profile, campaign goal/topic, and desired end states. Do not cache
across runs; always read fresh so file edits apply immediately without skill reload or server restart.

Expected config path (server-managed): `outreach/config/conversation_planner.json`

Use config fields when composing:
- `persona.name`, `persona.role`, `persona.organization`, `persona.specialization`
- `organization.description`
- `campaign.goal`, `campaign.topic`, `campaign.value_proposition`
- `conversation_end_goals.preferred[]` / `fallback[]` (their `id` values can be custom)
- `message_rules` limits and phrasing constraints

If a field is missing, fall back to the behavior currently documented in this skill.

---

## Schemas

All prospect and conversation payloads must conform to the canonical schemas (for validation and
field meanings). The agent does **not** open schema files by path unless the operator explicitly
allows it; rely on documented fields below and MCP-returned JSON.

| Record | Schema (reference) |
|--------|-------------------|
| Prospect | `outreach/schemas/prospect.schema.json` |
| Conversation | `outreach/schemas/conversation.schema.json` |

### Outreach filesystem MCP tools (authoritative I/O)

| Tool | Use |
|------|-----|
| `get_connections` | Load the connections list (returns JSON text; parse `connections` array). |
| `is_first_degree_connection` | Check DM-ready (1st-degree) status for a profile URL; used by **sync-pending-connections** to flip `pending` → `connected`. |
| `get_prospect` | Load one prospect by `prospect_id`. On `error: prospect not found`, stop or branch per operator. |
| `get_conversation` | Load one conversation by `prospect_id`. If missing, initialise a new object in memory that matches the conversation schema, then `upsert_conversation` when persisting. |
| `upsert_conversation` | Persist the full conversation object: pass `prospect_id` and `conversation` = **stringified JSON** of the whole document. |
| `upsert_prospect` | Persist the full prospect object the same way when `outreach_stage` (or other fields) must change. |
| `save_connection` | Upsert one row in the connections list (used heavily by send-connection-request; planner may use after intros). |
| `append_action_log` | Append one JSON object line to the actions log (`entry` = stringified JSON). |
| `append_planned_message_log` | Append one PlannedMessage object (`entry` = stringified JSON). |
| `save_outreach_report` | Write markdown body for end-of-sequence reports (`prospect_id`, `content`). |
| `remove_pending_queue_entry` | Remove a prospect from `pending.json` when the pipeline uses the queue. |

---

## Inputs

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `prospect_id` | string | no | Single-prospect run. **Omit to run batch mode** over all connections from `get_connections`. |
| (echo) | — | — | Surface PlannedMessage JSON to the user if helpful; **persistence** is always `append_planned_message_log`. |

### Loading records (MCP only)

**Single-prospect mode** (`prospect_id` provided):

1. `get_prospect(prospect_id)` → parse JSON → `prospect` (abort if tool returns `error: ...`).
2. `get_conversation(prospect_id)` → if success, parse → `conversation`; if `error: conversation not found`, build a minimal valid in-memory `conversation` with `prospect_id`, `outreach_stage`, `messages: []`, etc., then persist with `upsert_conversation` when appropriate.

**Batch mode** (`prospect_id` omitted — see [Batch Mode](#batch-mode) below):

1. `get_connections()` → parse → `connections` array.
2. For each entry, derive `prospect_id` and run the full single-prospect workflow.

---

## LinkedIn sequence workflow (MCP + state-updater + planner)

Use this as the default end-to-end runbook. **Phases A–D** map to MCP calls and the companion
**state-updater** skill (`outreach/skills/state-updater/SKILL.md`).

### Phase A — Sync thread from LinkedIn

1. Take `prospect.linkedin_url` as `profile_url`.
2. Call MCP **`fetch_chat_history`** (`profile_url`, optional `cdp_url` if not default). Parse the
   JSON array `[{ "message": string, "self": boolean }, ...]` (`self` = logged-in user).
3. Apply **state-updater** step 2: map `self: true` → `sender: "operator"`, `self: false` →
   `sender: "prospect"`, `text` = `message`; assign stable ISO timestamps for new rows; merge into
   `conversation.messages` without duplicating existing lines.
4. Persist merged thread: **`upsert_conversation(prospect_id, json.dumps(conversation))`** so local
   state matches LinkedIn before planning.
5. Optionally run intent classification and `next_action` **hints** from state-updater steps 3–6 when
   they help (disinterest, conversion). The **5-step sequence state machine below remains authoritative**
   for what to send next; reconcile conflicts in favour of terminal outcomes (`not_interested`,
   `mark_dead`, resume/email captured) when the thread clearly demands it.


### Phase B — Plan (this skill’s core)

1. Ensure `prospect` and `conversation` are current (after Phase A, use in-memory objects or call
   `get_prospect` / `get_conversation` again if another tool may have changed files).
2. Apply **Inputs → The Outreach Sequence**, **State Machine**, and **Composing the Message** below.
3. Perform **Side Effects** (below): build the updated `conversation` object, then
   **`upsert_conversation`**. For end-of-sequence, **`save_outreach_report`** then upsert conversation
   with `report_path` set to the canonical relative string `outreach/storage/reports/<prospect_id>.md`.
4. Emit **PlannedMessage** JSON: **`append_planned_message_log(entry=json.dumps(...))`** and echo to
   the user if useful.

### Phase C — Deliver (MCP)

Only when `planned_message` is non-null and the run should send:

| `next_action` | MCP tool | Parameters |
|---------------|----------|------------|
| `send_followup_message` | **`send_message`** | `profile_url` = `prospect.linkedin_url`, `message` = `planned_message` |
| `send_connection_request` | **`send_connection_request`** | `profile_url`, `note` = connection note (Step 1, ≤300 chars) |

Do **not** call `send_message` for connection-request flows; use `send_connection_request` with the note.

If MCP returns an error string instead of success (`ok` / `[MOCK] ok`), log the failure, **do not**
pretend the message was delivered, and leave `planned_message` in place for retry unless the operator
directs otherwise.

### Phase D — Post-delivery bookkeeping

After a **successful** send:

1. Update the in-memory `conversation` object: set `last_action` to the action you executed
   (`send_followup_message` or `send_connection_request`), `last_action_timestamp` to ISO 8601 UTC
   **now**, and `planned_message` to `null` (and `connection_note` already set if applicable).
2. **`upsert_conversation(prospect_id, json.dumps(conversation))`**.
3. **`append_action_log(entry=json.dumps({...}))`** e.g.
   `{ "action": "message_sent", "prospect_id": "<id>", "last_action": "<action>", "timestamp": "<ISO>" }`.
4. If `conversation.outreach_stage` changed, merge the same `outreach_stage` into `prospect` and call
   **`upsert_prospect(prospect_id, json.dumps(prospect))`**.
5. If the pipeline uses the pending queue, **`remove_pending_queue_entry(prospect_id)`** when
   appropriate.

### Modes

- **Full sequence (default):** Phase A → B → C (if applicable) → D.
- **Plan-only:** Phase B only (no MCP); useful when Chrome is offline.
- **Sync-only:** Phase A (+ state-updater logging) only; no PlannedMessage send.

---

## The Outreach Sequence

The sequence has five steps. Each run sends **exactly one step** — never two.

| Step | Name | Sequence step value | Outreach stage after send |
|------|------|---------------------|---------------------------|
| 1 | Intro | 1 | `pending_connection` (if connection request) or `engaged` |
| 2 | Career Deep-Dive | 2 | `engaged` |
| 3 | Career Plan | 3 | `engaged` |
| 4 | The Ask | 4 | `engaged` |
| 5 | The Close | 5 | `converted` → then `ended` |

### Step 1 — Intro

**Goal:** Introduce yourself using configured persona/org and invite them to explore the configured campaign goal/topic.

- Introduce yourself using `persona.name` and `persona.organization`.
- One sentence on what the organization does using `organization.description`.
- Ask if they're open to exploring.
- If `connection_status == "none"`: this message becomes the **connection request note** (≤ 300 characters hard limit).
- If already connected: send as a regular DM (≤ 500 characters).
- Reference one specific signal (post, career move, shared connection).

### Step 2 — Career Deep-Dive

**Goal:** Learn about their career journey and current focus.

- Reference specific roles, companies, transitions, or posts from `recent_posts`.
- Ask about their current work and what excites them most right now.
- Conversational tone — not an interview.
- ≤ 500 characters.

### Step 3 — Career Plan

**Goal:** Understand their trajectory and what they are looking for next relative to the configured campaign topic.

- Build on their Step 2 reply.
- Ask about future plans aligned with `campaign.topic` (for example startup roles, enterprise roles, advisory, or founder paths).
- Keep it open-ended so they share honestly.
- ≤ 500 characters.

### Step 4 — The Ask

**Goal:** Progress toward a configured preferred end goal.

Choose based on conversation signals and `conversation_end_goals.preferred`:

**Path A — Resume ask** (when `resume_received` or equivalent custom goal is preferred and they signal openness):
- Ask if they would be willing to share their resume.
- Frame it as helping match them with the right opportunities under `campaign.goal`.
- ≤ 500 characters.

**Path B — Email / call ask** (when call-oriented goal is preferred or they prefer a conversation):
- Offer to introduce them to Congxing Cai, our partner, for a quick call.
- Ask for their preferred email.
- ≤ 500 characters.

### Step 5 — The Close

**Goal:** Confirm the handoff and end the sequence.

**If resume shared (or equivalent configured handoff artifact):**
- Thank them and confirm you will review and connect them with relevant teams.
- Set `ended_reason` to matching configured goal ID (default `"resume_received"`).

**If email / call scheduled (or equivalent configured meeting goal):**
- Confirm the intro is coming.
- Note any scheduling details in `stage_history`.
- Set `ended_reason` to matching configured goal ID (default `"call_scheduled"`).

**If not interested:**
- End warmly, leave the door open.
- Set `ended_reason` to a configured fallback ID (default `"not_interested"`).

---

## State Machine

Use the table below to determine which step to execute (or whether to end without sending).

| Conversation state | `sequence_step` | Action |
|--------------------|-----------------|--------|
| No messages sent | null | Send Step 1 |
| Step 1 sent, prospect replied positively | 1 | Send Step 2 |
| Step 1 sent, no reply after ≥ 2 days | 1 | End — `no_response` |
| Step 1 sent via connection note, no reply yet | 1 | Wait — do nothing |
| Step 2 sent, prospect replied | 2 | Send Step 3 |
| Step 2 sent, no reply after ≥ 2 days | 2 | End — `no_response` |
| Step 3 sent, prospect replied | 3 | Send Step 4 |
| Step 3 sent, no reply after ≥ 2 days | 3 | End — `no_response` |
| Step 4 sent, prospect replied | 4 | Send Step 5 |
| Step 4 sent, no reply after ≥ 2 days | 4 | End — `no_response` |
| Step 5 sent or sequence naturally closed | 5 | End — appropriate reason |
| Prospect expressed disinterest at any point | any | End — `not_interested` |
| Resume / email / call captured | any | Send Step 5 (close) then End |

"No reply after ≥ 2 days" means `last_action_timestamp` is > 48 hours before the current UTC time and there are no new prospect messages after that timestamp.

---

## Composing the Message

Apply these rules to **every message**:

- Reference at least one specific detail from `recent_posts` or `notes`.
- Never open with "I came across your profile", "hope this message finds you", "reaching out to connect", or "touching base".
- Do not use: "synergy", "I'd love to pick your brain", "circle back", "bandwidth".
- Include the prospect's first name somewhere in the message.
- Sound like a real person wrote it for this one person — not a template.
- Tone: warm, professionally curious, low-pressure.
- Before finalising: ask yourself *would a real person actually send this?* If it reads like a template, rewrite it.

Character limits:
- Connection request note (Step 1, `connection_status == "none"`): **≤ 300 characters** (LinkedIn hard limit — count exactly).
- All other messages: **≤ 500 characters**.

---

## Side Effects (in-memory object → MCP persist; then Phase C send)

Mutate a single **`conversation`** dict in memory, then persist with **`upsert_conversation`** — never
by writing a path yourself. In a **full workflow**, apply the updates once the plan is final, emit
PlannedMessage via **`append_planned_message_log`**, then run **Phase C–D**.

### 1. Update the conversation record

After composing the message, set on **`conversation`**:

- `planned_message` → composed message text.
- `next_action` → appropriate action:
  - Step 1, `connection_status == "none"` → `"send_connection_request"`
  - Step 1, already connected → `"send_followup_message"`
  - Steps 2–4 → `"send_followup_message"`
  - Step 5 (close) → `"send_followup_message"`
  - End without sending → `"mark_ended"` or `"mark_dead"`
- `next_action_after` → `null` unless a deliberate delay.
- Step 1 + connection note → `connection_note` = message text.
- Advance `outreach_stage` (see state machine).
- Append to `stage_history`: `{ "stage": "<new_stage>", "entered_at": "<ISO UTC now>", "reason": "<brief reason>" }`.
- `sequence_step` → step just planned.

Then: **`upsert_conversation(prospect_id, json.dumps(conversation))`**.

### 2. End-of-sequence side effects (only when ending)

When the sequence ends (`ended_reason` is set; can be default or custom config value):

a. **Terminal fields** on **`conversation`**:
   - `ended_at`, `ended_reason`, `outreach_stage` → `"ended"` or `"dead"`, `next_action` → `null`,
     `planned_message` → `null`

b. **`save_outreach_report(prospect_id, content)`** with markdown body:

```
# LinkedIn Outreach Report: <Full Name>

Profile:  <linkedin_url>
Date:     <YYYY-MM-DD>
Status:   <Ended — Resume Received | Ended — Call Scheduled | Ended — Not Interested | Ended — No Response>
Sequence reached: Step <n>

## Profile Summary
- <headline / title>
- <current role and company>
- <key skills or domain expertise>

## Conversation Summary
<2–4 sentences summarising the thread: what was discussed, what signals emerged>

## Career Plans
<What the prospect shared about their next steps, if anything>

## Outcome
- Resume: <path to saved file or "Not shared">
- Email: <their email or "Not shared">
- Call: <scheduled details or "Not scheduled">

## Notes
<Any additional context useful for future outreach or handoff>
```

   - Set `report_path` on **`conversation`** to `outreach/storage/reports/<prospect_id>.md` (schema-relative string).
   - **`upsert_conversation`** again with the updated object.

c. **`append_action_log(entry=json.dumps({...}))`**:
```json
{ "action": "conversation_ended", "prospect_id": "<id>", "ended_reason": "<reason>", "sequence_step": <n>, "timestamp": "<ISO UTC>" }
```

d. Sync **`prospect.outreach_stage`** with **`upsert_prospect`** if needed.

---

## Output — PlannedMessage

Build the PlannedMessage object, then **`append_planned_message_log(entry=json.dumps(planned_message))`**.
Optionally print the same JSON for the operator; file logging must go through the MCP tool.

```json
{
  "prospect_id":    "<id>",
  "stage":          "<outreach_stage after planning>",
  "sequence_step":  <1–5 or null>,
  "action":         "<next_action value>",
  "message":        "<exact message text, or null if ending without a send>",
  "end_conversation": <true | false>,
  "ended_reason":   "<reason code or null>",
  "generated_at":   "<ISO 8601 UTC>",
  "char_count":     <integer or null>
}
```

`message` is null only when `end_conversation` is true and there is no final closing message to send (e.g., prospect said not interested after the close was already sent).

---

## Example Invocations

### Fresh prospect — Step 1

```
Run conversation-planner with prospect_id = "alex_chen_softeng"
```

Expected: Step 1 message (connection note ≤ 300 chars), `next_action = "send_connection_request"`.

### Prospect replied — Step 2

```
Run conversation-planner with prospect_id = "alex_chen_softeng"
# Phase A: fetch_chat_history → merge their reply into messages
# Phase B–D: plan Step 2, send_message with planned text, update last_action
```

Expected: Step 2 career deep-dive message, `next_action = "send_followup_message"`, MCP `send_message` succeeds, bookkeeping completed.

### No reply after 2 days

```
Run conversation-planner with prospect_id = "alex_chen_softeng"
# (last_action_timestamp is > 48h ago, no new prospect messages)
```

Expected: `end_conversation = true`, `ended_reason = "no_response"`, `message = null`, report saved.

---

## Batch Mode

When `prospect_id` is **not** provided, run planning for every connection returned by **`get_connections()`**.

### Steps

1. **`get_connections()`** → parse JSON. If `connections` is missing or empty, stop and report:  
   `"No connections in project data. Add connections (e.g. send connection requests) first."`

2. **Filter actionable connections.**  
   Optionally run **`sync-pending-connections`** (`outreach/skills/sync-pending-connections/SKILL.md`) first so accepted invites are promoted from `"pending"` to `"connected"` before this step.  
   Skip entries where any of the following is true:
   - `connection_status` is `"pending"` — invitation not yet accepted; nothing to plan.
   - **`get_conversation(prospect_id)`** shows `outreach_stage` is `"ended"` or `"dead"` — sequence is complete.
   - Same conversation has `next_action` `"mark_ended"` or `"mark_dead"`.

3. **For each remaining connection, run the full single-prospect workflow** (Phases A → B → C → D):
   - Derive `prospect_id` from the connection entry's `prospect_id` field.
   - If `prospect_id` is `null` (connection added outside the pipeline), skip and log a warning.
   - Run the workflow exactly as described in [LinkedIn sequence workflow](#linkedin-sequence-workflow-mcp--state-updater--planner).
   - **One outbound touch per prospect per run** — the single-touch constraint still applies per prospect.
   - Collect the `PlannedMessage` result (or end-of-sequence outcome) for the summary.

4. **Print a batch run summary** after all prospects are processed:

```
── Batch Planner Run ─────────────────────────────────────────
Run at:    <ISO UTC timestamp>
Total:     <N> connections loaded
Skipped:   <N> (pending acceptance / already ended / no prospect_id)
Processed: <N>
  ✓ Sent:  <N>   (list of names + actions)
  ✗ Error: <N>   (list of names + error reasons)
  → Ended: <N>   (list of names + ended_reason)
─────────────────────────────────────────────────────────────
```

5. **`append_action_log`** with a batch summary object, e.g.:
```json
{ "action": "batch_plan_run", "timestamp": "<ISO UTC>", "total": <N>, "sent": <N>, "errors": <N>, "ended": <N> }
```

### Batch mode notes

- Process connections **sequentially**, not in parallel — LinkedIn rate limits apply.
- If any single prospect run hits an MCP error (bot detection, Chrome offline, etc.), log it in the summary but **continue** to the next prospect rather than aborting the whole batch.
- Batch mode honours all single-prospect constraints: one touch per prospect, never skip a step, no automatic retry on failure.

---

## Test and fixture data (do not corrupt)

- **`tests/` is off-limits for outreach writes.** Under `tests/` — especially `tests/fixtures/` (e.g.
  `tests/fixtures/conversation-planner/`) — files exist for automated tests. Do **not** edit, delete,
  move, or overwrite them while running this skill unless the user explicitly asked you to change
  **test code or fixtures**.
- **Do not import fixtures into the live pipeline.** Never copy JSON from `tests/fixtures/` into
  `upsert_conversation`, `upsert_prospect`, or browser sends. MCP persistence targets the operational
  `outreach/` tree only; fixtures are outside that tree and are not loaded by `get_*` tools.
- **Prospect IDs:** If an id matches a fixture basename used only in tests, confirm with the operator
  before writing production pipeline data under that id.

---

## Important constraints

- **MCP only for LinkedIn automation.** Use `fetch_chat_history`, `send_message`, and
  `send_connection_request` — no ad-hoc scraping or undocumented APIs.
- **MCP only for outreach data I/O.** Use `get_*`, `upsert_*`, `append_*`, `save_outreach_report`,
  `save_connection`, `remove_pending_queue_entry` — **never** construct `outreach/...` paths or use
  workspace file tools for these records.
- **One outbound touch per run.** Never compose or send two sequence steps in a single execution.
- **Never skip a step.** Do not jump from Step 1 to Step 3.
- **Never retry automatically** after an MCP failure; report the error and stop or wait for operator input.
- **Prospect stage:** When `conversation.outreach_stage` changes, update `prospect` and **`upsert_prospect`** unless the operator forbids it.
