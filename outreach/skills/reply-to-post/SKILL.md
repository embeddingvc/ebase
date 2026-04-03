---
name: reply-to-post
description: Leave a comment (reply) on a LinkedIn post via the MCP reply_to_post tool. Use when the user asks to comment on, reply to, or engage with a LinkedIn post.
---

# Reply to Post

Leave a comment on a LinkedIn post by calling the `reply_to_post` MCP tool.

## When to Use

- User asks to comment on, reply to, or engage with a specific LinkedIn post
- Part of an engagement sequence (e.g. react first, then comment)
- Outreach strategy involves engaging with a prospect's content before connecting

## Inputs

- `post_url` (required) — direct URL of the LinkedIn post or activity item
- `comment` (required) — comment text to post

## Pre-flight Checks

Before calling the tool, verify:
1. The `post_url` points to a specific post (contains `/posts/`, `/pulse/`, or `/activity/`). If only a profile URL is given, instruct the user to navigate to the post and share the direct URL.
2. The comment is appropriate, relevant, and has been reviewed by the operator. Do **not** auto-generate and post without confirmation.

## Steps

### 1. Confirm with the operator

Display the post URL and the comment text and ask for explicit confirmation:

```
Post the following comment on <post_url>?

"<comment text>"

Reply yes to confirm or no to cancel.
```

Wait for a "yes" / "confirm" response before proceeding.

### 2. Call the MCP tool

```
Tool: reply_to_post
  post_url: <the post URL>
  comment:  <the comment text>
```

The tool attaches to the running Chrome session, navigates to the post, opens the comment composer, types the comment at human-like speed, and submits it.

### 3. Handle the response

| Response | Meaning                          | Action                                        |
|----------|----------------------------------|-----------------------------------------------|
| `"ok"`   | Comment posted successfully      | Log the action; print confirmation (see below) |
| anything else | Post failed (button not found, page error, etc.) | Report the error; do NOT retry automatically |

### 4. Print confirmation

On success:

```
── Comment Posted ────────────────────────────────────────────
Post:     <post_url>
Posted at: <current ISO timestamp>
Preview:  "<first 80 chars of comment> …"
─────────────────────────────────────────────────────────────
```

### 5. Log the action (if using outreach pipeline)

Append to `outreach/logs/actions.jsonl`:
```json
{ "action": "comment_posted", "post_url": "<url>", "timestamp": "<ISO>", "char_count": <n> }
```

If this comment is part of a prospect's outreach sequence, update their conversation file:
- Append to `messages`: `{ "sender": "operator", "text": "<comment>", "timestamp": "<ISO>", "context": "post_comment", "post_url": "<url>" }`

## Example

**User:** "Comment on https://www.linkedin.com/posts/alexchen_ai-activity-123/ — say this is great insight"

```
Post the following comment on https://www.linkedin.com/posts/alexchen_ai-activity-123/?

"Great insight, Alex — the point about AI adoption timelines really resonates with what we're seeing too."

Reply yes to confirm or no to cancel.
```

**User:** "yes"

```
Tool call → reply_to_post(post_url="https://…/posts/alexchen_ai-activity-123/", comment="Great insight …")

── Comment Posted ────────────────────────────────────────────
Post:      https://www.linkedin.com/posts/alexchen_ai-activity-123/
Posted at: 2026-04-03T14:05:00+00:00
Preview:   "Great insight, Alex — the point about AI adoption timelines …"
─────────────────────────────────────────────────────────────
```

## Error Handling

- **Comment button not found** — tool returns an error string. This may mean the post has comments disabled or the page didn't load correctly. Report: `"Could not post comment — the Comment button was not found. The post may have comments disabled, or the URL may be incorrect."`
- **Chrome not running** — CDP connection fails. Report: `"Could not connect to Chrome. Make sure Chrome is running with --remote-debugging-port=9222."`
- **Not logged in** — tool raises an error. Report: `"Not logged in to LinkedIn. Log in manually in the Chrome window and retry."`
- **Bot detection** — if posting fails with a timeout, stop immediately and report: `"LinkedIn may have triggered bot detection. Wait a few minutes before retrying."`
- **Wrong URL format** — if the URL looks like a profile rather than a post, report: `"That looks like a profile URL, not a post URL. Please navigate to the specific post and share its URL (it should contain /posts/, /pulse/, or /activity/)."`
