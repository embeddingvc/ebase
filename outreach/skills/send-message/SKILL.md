---
name: send-message
description: Send a direct LinkedIn message to a 1st-degree connection via the MCP send_message tool. Use when the user asks to message, DM, or write to a LinkedIn contact.
---

# Send Message

Send a direct message to an existing 1st-degree LinkedIn connection by calling the `send_message` MCP tool.

## Test and fixture data (do not corrupt)

- Do **not** modify `tests/` or `tests/fixtures/` when sending messages or updating pipeline state.
- Persist conversation updates only via MCP **`get_conversation`** / **`upsert_conversation`** and logs via
  **`append_action_log`** — never copy fixture JSON into those calls unless the user asked to edit tests.

## When to Use

- User asks to send a message, DM, or follow-up to a LinkedIn connection
- Downstream step after `scrape-profile` has confirmed the prospect is a 1st-degree connection
- Part of a larger outreach sequence (run Message Planner first to generate the text)

## Inputs

- `profile_url` (required) — full LinkedIn profile URL, e.g. `https://www.linkedin.com/in/username/`
- `message` (required) — message body to send (LinkedIn limit: ~8 000 chars)

## Pre-flight Checks

Before calling the tool, verify:
1. The prospect is a 1st-degree connection (`connection_degree == 1`). If not, abort and suggest sending a connection request first.
2. The message is under 8 000 characters.
3. The message has been reviewed and is ready to send (do **not** auto-generate and send without operator confirmation).

## Steps

### 1. Call the MCP tool

```
Tool: send_message
  profile_url: <the LinkedIn URL>
  message:     <the message text>
```

The tool attaches to the running Chrome session, navigates to the profile, types the message at human-like speed, and submits it.

### 2. Handle the response

| Response | Meaning                          | Action                                     |
|----------|----------------------------------|--------------------------------------------|
| `"ok"`   | Message sent successfully        | Log the send; print confirmation (see below) |
| anything else | Send failed (not a 1st-degree connection, button not found, etc.) | Report the error to the operator; do NOT retry automatically |

### 3. Print confirmation

On success:

```
── Message Sent ─────────────────────────────────────────────
To:       <Name> (<profile_url>)
Sent at:  <current ISO timestamp>
Preview:  "<first 80 chars of message> …"
─────────────────────────────────────────────────────────────
```

### 4. Update conversation state (if using outreach pipeline)

When you have `prospect_id`:

1. **`get_conversation(prospect_id)`** → parse `conversation` (skip this block if no pipeline id).
2. Append to `conversation.messages`:
   `{ "sender": "operator", "text": "<message>", "timestamp": "<ISO UTC>" }` (conversation schema only).
3. Set `last_action` → `"send_followup_message"`, `last_action_timestamp` → now, `next_action` → `null`
   until the planner sets a new one.
4. **`upsert_conversation(prospect_id, json.dumps(conversation))`**
5. **`append_action_log(entry=json.dumps({...}))`**:
```json
{ "action": "message_sent", "prospect_id": "<id>", "timestamp": "<ISO>", "char_count": <n> }
```

## Example

**User:** "Message https://www.linkedin.com/in/alexchen/ — say thanks for connecting"

```
Send the following message to Alex Chen (https://www.linkedin.com/in/alexchen/)?

"Hi Alex — thanks so much for connecting! Looking forward to staying in touch."

Reply yes to confirm or no to cancel.
```

**User:** "yes"

```
Tool call → send_message(profile_url="https://www.linkedin.com/in/alexchen/", message="Hi Alex — …")

── Message Sent ─────────────────────────────────────────────
To:       Alex Chen (https://www.linkedin.com/in/alexchen/)
Sent at:  2026-04-03T14:00:00+00:00
Preview:  "Hi Alex — thanks so much for connecting! Looking forward to …"
─────────────────────────────────────────────────────────────
```

## Error Handling

- **Not a 1st-degree connection** — tool returns an error string. Report: `"Cannot send a direct message to <Name> — they are not a 1st-degree connection. Use send_connection_request first."`
- **Chrome not running** — CDP connection fails. Report: `"Could not connect to Chrome. Make sure Chrome is running with --remote-debugging-port=9222."`
- **Not logged in** — tool raises an error. Report: `"Not logged in to LinkedIn. Log in manually in the Chrome window and retry."`
- **Bot detection** — if the send fails with a timeout or unexpected page state, stop immediately and report: `"LinkedIn may have triggered bot detection. Wait a few minutes before retrying."`
