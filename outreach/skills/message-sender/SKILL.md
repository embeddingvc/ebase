# Message Sender Skill

## Purpose
Send a pre-planned message to a LinkedIn prospect via browser automation.
This skill is EXECUTION ONLY — it does not generate message content.
Always run Message Planner first to get the message text.

## Inputs
- `prospect_id`: used to look up the prospect and conversation files
- `message`: the exact text to send (from message planner output)
- `action`: one of `send_connection_request` | `send_message`

## Pre-flight Checks (run before any browser action)
1. Load `outreach/queue/pending.json` — confirm this prospect+action is queued.
2. Load `outreach/conversations/<prospect_id>.json` — confirm `next_action` matches the requested action.
3. Check the action log for today's send count. If sends today ≥ 15, abort and report: "Daily send limit reached."

## Steps for `send_connection_request`
1. Navigate to prospect's LinkedIn URL (from prospect JSON).
2. Find and click the "Connect" button.
3. If a note dialog appears, click "Add a note" and type the message (≤300 chars).
4. Click "Send invitation".
5. Verify: confirmation toast or button changes to "Pending".

## Steps for `send_message`
1. Navigate to prospect's LinkedIn URL.
2. Click the "Message" button.
3. In the message compose box, type the message.
4. Click "Send".
5. Verify: message appears in the thread.

## Post-send State Update
After a successful send, update `outreach/conversations/<prospect_id>.json`:
- Append to `messages`: `{ "sender": "operator", "text": "<message>", "timestamp": "<ISO>" }`
- Set `last_action` to the action just performed
- Set `last_action_timestamp` to now
- Set `next_action` to `null` (wait for reply before planning next step)
- Advance `outreach_stage` if appropriate

Append to `outreach/logs/actions.jsonl`:
```json
{ "action": "message_sent", "prospect_id": "<id>", "action_type": "<type>", "timestamp": "<ISO>", "char_count": <n> }
```

Remove prospect from `outreach/queue/pending.json`.

## Error Handling
- If "Connect" button not found: check if already connected or pending. Update state accordingly.
- If message send fails: do NOT retry automatically. Log the failure and stop.
- If any bot detection warning appears: stop immediately. Log and report to operator.
