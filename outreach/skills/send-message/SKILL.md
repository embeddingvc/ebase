---
name: send-message
description: Send a direct LinkedIn message to a 1st-degree connection via the MCP send_message tool. Use when the user asks to message, DM, or write to a LinkedIn contact.
---

# Send Message

Send a direct message to an existing 1st-degree LinkedIn connection by calling the `send_message` MCP tool.

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

### 1. Confirm with the operator

Display the recipient and the message text and ask for explicit confirmation before calling the tool:

```
Send the following message to <Name> (<profile_url>)?

"<message text>"

Reply yes to confirm or no to cancel.
```

Wait for a "yes" / "confirm" response before proceeding.

### 2. Call the MCP tool

```
Tool: send_message
  profile_url: <the LinkedIn URL>
  message:     <the message text>
```

The tool attaches to the running Chrome session, navigates to the profile, types the message at human-like speed, and submits it.

### 3. Handle the response

| Response | Meaning                          | Action                                     |
|----------|----------------------------------|--------------------------------------------|
| `"ok"`   | Message sent successfully        | Log the send; print confirmation (see below) |
| anything else | Send failed (not a 1st-degree connection, button not found, etc.) | Report the error to the operator; do NOT retry automatically |

### 4. Print confirmation

On success:

```
── Message Sent ─────────────────────────────────────────────
To:       <Name> (<profile_url>)
Sent at:  <current ISO timestamp>
Preview:  "<first 80 chars of message> …"
─────────────────────────────────────────────────────────────
```

### 5. Update conversation state (if using outreach pipeline)

If a conversation file exists at `outreach/conversations/<prospect_id>.json`:
- Append to `messages`: `{ "sender": "operator", "text": "<message>", "timestamp": "<ISO>" }`
- Set `last_action` → `"send_message"`, `last_action_timestamp` → now
- Set `next_action` → `null` (wait for reply before planning next step)

Append to `outreach/logs/actions.jsonl`:
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
