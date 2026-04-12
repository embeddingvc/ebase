# State Updater Skill

## Purpose
After a prospect replies (or before planning the next touch), sync the LinkedIn DM thread into local JSON and refresh conversation state.
Determines what the next action should be and queues it.

## Test and fixture data (do not corrupt)

- Do **not** read or modify files under `tests/` or `tests/fixtures/` as part of this skill. Fixtures
  are for test runners only; live state is **`get_*` / `upsert_*`** under the project `outreach/` tree.
- Never hydrate `upsert_conversation` or `upsert_prospect` from fixture JSON unless the user explicitly
  asked to **edit tests**, not to run outreach.

## Inputs
- `prospect_id`: load **`get_prospect(prospect_id)`** → parse `linkedin_url` (MCP tools in `tools/server.py`; do not construct paths).

## Steps
1. Call the LinkedIn MCP tool **`fetch_chat_history`** with `profile_url` = `linkedin_url` from the prospect record (Chrome must be attached). Parse the returned JSON array of `{ "message", "self" }`.
2. **`get_conversation(prospect_id)`** → parse into `conversation` (or initialise if not found). Map each fetched row to the conversation schema: `sender` = `"operator"` if `self` is true, else `"prospect"`; `text` = `message`. For `timestamp`, use ISO 8601 UTC with +1s offsets from a `sync_started_at` for ordering. Merge into `conversation.messages`: append only **new** rows versus existing entries (avoid duplicates on re-sync). Use the merged thread plus `last_action_timestamp` to detect *new* prospect replies. Persist with **`upsert_conversation(prospect_id, json.dumps(conversation))`**.
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

5. Update `outreach_stage` in the prospect record to match new state → **`upsert_prospect(prospect_id, json.dumps(prospect))`**.

6. If a resume link or email address is visible in the thread, record it in `conversation` and **`upsert_conversation`** again.

7. **`append_action_log(entry=json.dumps({...}))`**:
```json
{ "action": "state_updated", "prospect_id": "<id>", "reply_intent": "<intent>", "next_action": "<action>", "timestamp": "<ISO>" }
```
