---
name: sync-planner-persona-from-linkedin
description: Refresh conversation planner identity from LinkedIn by calling MCP parse_profile (structured crawl), synthesizing persona and organization prose in your reasoning, then writing config via merge_conversation_planner_identity (never heuristic server-side summarization). Use when the operator sets up persona, syncs from their profile, or wants specialization/description grounded in experience, education, skills, and activity.
---

# Sync Planner Persona From LinkedIn

Align `outreach/config/conversation_planner.json` **persona** and **organization** with a LinkedIn member profile using **`parse_profile`** for data and **`merge_conversation_planner_identity`** for persistence. Summarization is done **by you** (the Skill / model), not inside the MCP server.

**Filesystem rule:** Never read or write `outreach/config/` via raw paths or shell. Use **`get_conversation_planner_config`**, **`merge_conversation_planner_identity`**, or full **`upsert_conversation_planner_config`** through MCP only.

---

## When to use

- First-time persona setup before running **conversation-planner**
- Operator asks to “sync my planner from LinkedIn”, “refresh identity from profile”, “pull skills/experience into specialization”

---

## Inputs

- **`profile_url`** — Full `https://www.linkedin.com/in/…/` URL.
  - For the **signed-in member**, use **`https://www.linkedin.com/in/me/`** (LinkedIn redirects to their public slug).
  - Optionally confirm with **`get_conversation_planner_config`** after merge.

**Live prerequisites:** Same as other browser tools (`make browser`, Chrome CDP `9222`, logged into LinkedIn). **`parse_profile`** is slower than **`scrape_profile`** (experience, education, skills, activity crawl).

---

## Workflow (mandatory order)

### 1. Fetch structured profile

Call MCP **`parse_profile`** with `profile_url` (and defaults for `max_activity_posts` unless the operator narrows breadth).

Parse the JSON envelope (`linkedin.parse_profile/v2`). Prefer:

| Section | Planner use |
|---------|-------------|
| `subject.identity` | `persona.name`, headline hint for role/org |
| `subject.narrative.about` | Voice and facts for **specialization** / **organization.description** |
| `subject.career_signals` | Primary role, org, `skills_preview` |
| `relations.experience[]` | Current/recent titles, employers, tenure (prioritize parsed cards over headline when clearer) |
| `relations.education[]` | Schools, degrees — brief mention in synthesized copy |
| `relations.skills[]` | Thematic clustering for **specialization** (avoid dumping dozens of comma-separated skills unless concise) |
| `activity.updates[]` | Recent themes, topics of posts — summarize, do not paste long bodies |

Ignore `relations.mutual_connections` for persona copy unless the operator explicitly wants it referenced.

### 2. Draft identity for the planner (you)

Produce:

- **`persona.name`** — `subject.identity.full_name` when present.
- **`persona.role`** — Prefer `career_signals.primary_role` else best title from headline or top experience card.
- **`persona.organization`** — Prefer `career_signals.primary_organization` else headline / top experience employer.
- **`persona.specialization`** — Short paragraph (≤ ~500 chars) synthesizing strengths, domains, tech stack clues from **skills + experience + education + activity**, not a repetition of `{role} at {organization}` unless that is genuinely the entire signal.
- **`organization.description`** — Longer prose (≤ ~1200 chars) framing **who speaks for outbound** (employer/industry/context, geography, mission-relevant bullets) using About + strongest experience/education signals. This is prose for downstream planning, not a raw JSON dump.

If data is sparse, stay honest (“limited public profile”) and shorter.

Optional: briefly show the operator your drafted JSON objects before merging if they asked for review.

### 3. Persist (merge only identity)

Call MCP **`merge_conversation_planner_identity`**:

- **`persona_json`** — JSON object string with whichever of `name`, `role`, `organization`, `specialization` you are updating (you may send all four).
- **`organization_json`** — JSON object string, typically `{ "description": "…" }`.

Use **`{}`** for either argument to skip that block. Do not send unknown keys.

Example (illustrative — your strings differ):

```json
Tool: merge_conversation_planner_identity
persona_json: "{\"name\":\"…\",\"role\":\"…\",\"organization\":\"…\",\"specialization\":\"…\"}"
organization_json: "{\"description\":\"…\"}"
```

On success, parse the tool’s JSON return and confirm `ok: true`.

### 4. Verify

Call **`get_conversation_planner_config`** and ensure `persona` / `organization` match intent.

---

## Related MCP tools

| Tool | Role here |
|------|-----------|
| `parse_profile` | Source of truth for experience, education, skills, activity, about |
| `merge_conversation_planner_identity` | Safe partial write of identity fields |
| `get_conversation_planner_config` | Read-back / optional pre-merge context |
| `upsert_conversation_planner_config` | Only if the operator needs to replace the **entire** planner file (avoid for routine identity sync) |

Do **not** use **`scrape_profile`** alone for this Skill when you need skills/education/activity depth — use **`parse_profile`**.

---

## Campaign block

Do **not** overwrite `campaign`, `message_rules`, or `router` unless the operator asks. **`merge_conversation_planner_identity`** touches only `persona` and `organization`.
