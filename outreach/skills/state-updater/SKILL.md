# State Updater Skill

## Purpose
After a prospect replies, read the LinkedIn conversation thread and update conversation state.
Determines what the next action should be and queues it.

## Inputs
- `prospect_id`: used to look up files

## Steps
1. Navigate to LinkedIn Messages and find the thread for this prospect.
2. Read all new messages since `last_action_timestamp`.
3. Append new messages to `outreach/conversations/<prospect_id>.json` under `messages`.
4. Classify the reply intent:
   - `positive`: expressed interest, asked a question, mentioned openness to roles
   - `neutral`: generic acknowledgement, no clear signal
   - `negative`: not interested, asked to stop, no reply in 7+ days
   - `converted`: shared resume, email, or calendar link

5. Based on classification, set `next_action`:
   - `positive` → `send_followup_message` (queue immediately)
   - `neutral` → `send_followup_message` (queue after 2 days)
   - `negative` → `mark_dead` (remove from queue)
   - `converted` → `download_resume` or `confirm_meeting` depending on what was shared

6. Update `outreach_stage` in prospect JSON to match new state.

7. If a resume link or email address is visible in the thread, record it in the conversation JSON.

8. Append to `outreach/logs/actions.jsonl`:
```json
{ "action": "state_updated", "prospect_id": "<id>", "reply_intent": "<intent>", "next_action": "<action>", "timestamp": "<ISO>" }
```
