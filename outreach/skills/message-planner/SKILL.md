# Message Planner Skill

## Purpose
Given a prospect profile and conversation history, generate the next outreach message.
This skill has NO browser side effects — it only reads files and writes a message to stdout or a file.
It is safe to run in isolation for testing.

## Inputs
- Prospect JSON file path (required)
- Conversation JSON file path (required)
- Output file path (optional — if omitted, print to stdout)

## Behavior

1. Read the prospect JSON and conversation JSON from disk.
2. Determine the current `outreach_stage` and `next_action` from the conversation file.
3. Based on stage, generate the appropriate message:

   | Stage     | next_action              | Message goal                                      |
   |-----------|--------------------------|---------------------------------------------------|
   | cold      | send_connection_request  | Short, personalized connection note (≤300 chars)  |
   | engaged   | send_followup_message    | Brief intro + role description, ask for resume    |
   | replied   | send_followup_message    | Respond to their reply, move toward resume/call   |
   | converted | send_followup_message    | Confirm details, send calendar link if available  |

4. Rules for all messages:
   - Reference at least one specific detail from `recent_posts` or `notes`
   - Never sound like a mass template
   - Keep connection notes ≤300 characters (LinkedIn limit)
   - Keep followup messages ≤500 characters
   - Do not use phrases: "I came across your profile", "I'd love to pick your brain", "synergy"

5. Write output as JSON:
```json
{
  "prospect_id": "<id>",
  "stage": "<current stage>",
  "action": "<next_action>",
  "message": "<generated message text>",
  "generated_at": "<ISO timestamp>"
}
```

6. Save output to: `outreach/logs/planned_messages.jsonl` (append one line per run)

## Example Invocation
```
Read outreach/prospects/sample_alex_chen.json
Read outreach/conversations/sample_alex_chen.json
Run message planner skill
```
