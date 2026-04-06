# State Updater Skill

## Purpose
After a prospect replies (or before planning the next touch), sync the LinkedIn DM thread into local JSON and refresh conversation state.
Determines what the next action should be and queues it.

## Inputs
- `prospect_id`: used to look up files (`outreach/prospects/<prospect_id>.json` → `linkedin_url`)

## Steps
1. Call the LinkedIn MCP tool **`fetch_chat_history`** with `profile_url` = `linkedin_url` from the prospect file (Chrome must be attached; see `tools/server.py`). Parse the returned JSON array of `{ "message", "self" }`.
2. Map each row to the conversation schema: `sender` = `"operator"` if `self` is true, else `"prospect"`; `text` = `message`. For `timestamp`, use ISO 8601 UTC: assign increasing offsets (e.g. +1s per message in order) from a single `sync_started_at` so ordering is stable. Merge into `messages` in `outreach/conversations/<prospect_id>.json`: append only rows that are **new** versus existing entries (avoid duplicates on re-sync). Use the merged thread plus `last_action_timestamp` to detect *new* prospect replies.
3. Classify the reply intent (from the latest prospect messages and timing):
   - `positive`: expressed interest, asked a question, mentioned openness to roles
   - `neutral`: generic acknowledgement, no clear signal
   - `negative`: not interested, asked to stop, no reply in 7+ days
   - `converted`: shared resume, email, or calendar link

4. Based on classification, set `next_action`:
   - `positive` → `send_followup_message` (queue immediately)
   - `neutral` → `send_followup_message` (queue after 2 days)
   - `negative` → `mark_dead` (remove from queue)
   - `converted` → `download_resume` or `confirm_meeting` depending on what was shared

5. Update `outreach_stage` in prospect JSON to match new state.

6. If a resume link or email address is visible in the thread, record it in the conversation JSON.

7. Append to `outreach/logs/actions.jsonl`:
```json
{ "action": "state_updated", "prospect_id": "<id>", "reply_intent": "<intent>", "next_action": "<action>", "timestamp": "<ISO>" }
```
