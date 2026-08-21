---
name: ebase-sync-persona
description: Refresh planner identity in outreach/config/persona.json from LinkedIn by calling MCP parse_profile (structured crawl), synthesizing persona and organization prose in your reasoning, then writing persona.json directly and validating with tools/validate_outreach_config.py (never heuristic server-side summarization). Use when the operator sets up persona, syncs from their profile, or wants specialization/description grounded in experience, education, skills, and activity.
---

# Sync Planner Persona From LinkedIn

Align **`outreach/config/persona.json`** (**`persona`** and **`organization`**) with a LinkedIn member profile using **`parse_profile`** for data and a direct file write (validated by `tools/validate_outreach_config.py`) for persistence. Summarization is done **by you** (the Skill / model), not inside the MCP server.

## Browser tool policy (strict — read first)

Every browser action in this skill goes through the **LinkedIn MCP server** (tools prefixed
`mcp__linkedin__*`) and **only** that server. The LinkedIn MCP attaches to the operator's
logged-in Chrome over CDP on port `9222` with this project's rate-limits, human-like jitter,
and bot-detection safeguards — substituting any other browser surface defeats those guarantees
and can get the operator's LinkedIn account flagged.

Even if other browser tools are registered in the current Claude CLI session, do **not** use
them for this workflow:

- **No other browser MCPs.** Do not use `chrome-devtools`, `playwright`, `puppeteer`,
  `browser-use`, `browserbase`, `gstack` browser, or any other Chrome-attached MCP to open,
  click, type, or read on `linkedin.com`.
- **No "Claude in Chrome" extension / Chrome side-panel** to drive the browser on `linkedin.com`.
- **No `WebFetch`, `WebSearch`, `curl`, `wget`, `fetch`, `requests`, or `Bash`** against
  `linkedin.com` / `licdn.com`. The structured experience / education / activity crawl must come
  from `mcp__linkedin__parse_profile` only.
- **No manual operator hand-off** as a substitute for the parse. Call the LinkedIn MCP tool; on
  error, report the error verbatim and stop.

Allowed browser-side tool in this skill (LinkedIn MCP only): `mcp__linkedin__parse_profile`.

If `mcp__linkedin__parse_profile` is not registered in the current session, **stop and tell the
operator the LinkedIn MCP is not registered** (fix: run `./install.sh` or `make claude-install`,
then start a **new** Claude Code session — MCP servers only load at session start). Do **not**
pick up a different browser tool as a fallback.

**Filesystem rule:** Read and write **`outreach/config/persona.json`** directly with the Read /
Write tools (fall back to reading `persona.json.example` when the local file is absent) — no MCP
round trip. After writing, confirm with:

```bash
uv run python tools/validate_outreach_config.py --persona outreach/config/persona.json
```

This has no LinkedIn MCP dependency, so it works even before the MCP server has loaded in this
session — only the `parse_profile` crawl in step 1 needs it. Never touch
`conversation_planner.json` from this skill (see Campaign block below).

---

## System check (run first)

Before syncing, check service health and for a newer ebase version:

```bash
bin/outreach-update-check 2>/dev/null || true
```

Follow the inline flow in skill **`ebase-upgrade`** for every line printed:
`SERVICE_DOWN <service> <url>` (inform the user, non-blocking), then
`UPGRADE_AVAILABLE` (ask to upgrade), `UPGRADED`/`JUST_UPGRADED` (log and
continue), or `UP_TO_DATE`/empty (continue silently).
Do not block on network failures.

## When to use

- First-time persona setup before running **ebase-conversation-planner**
- Operator asks to “sync my planner from LinkedIn”, “refresh identity from profile”, “pull skills/experience into specialization”

---

## Inputs

- **`profile_url`** — Full `https://www.linkedin.com/in/…/` URL.
  - For the **signed-in member**, use **`https://www.linkedin.com/in/me/`** (LinkedIn redirects to their public slug).
  - Optionally confirm by reading **`outreach/config/persona.json`** after the write.

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

Read the current **`outreach/config/persona.json`** (fall back to `persona.json.example`, then the
hardcoded default identity if neither exists). Shallow-merge your drafted fields on top — only
overwrite whichever of `persona.name`, `persona.role`, `persona.organization`,
`persona.specialization`, `organization.description` you are updating; leave everything else in
the file untouched. Do not introduce unknown keys.

Write the merged object to **`outreach/config/persona.json`**, then validate:

```bash
uv run python tools/validate_outreach_config.py --persona outreach/config/persona.json
```

On `error: ...`, fix the draft and re-write.

### 4. Verify

Read **`outreach/config/persona.json`** back and ensure `persona` / `organization` match intent.

---

## Related tools

| Tool | Role here |
|------|-----------|
| `parse_profile` (MCP) | Source of truth for experience, education, skills, activity, about |
| `tools/validate_outreach_config.py` (Bash) | Confirms the written `persona.json` is well-formed |

Do **not** use **`scrape_profile`** alone for this Skill when you need skills/education/activity depth — use **`parse_profile`**.

---

## Campaign block

Do **not** overwrite `campaign`, `message_rules`, or `router` unless the operator asks. This skill only ever writes **`persona.json`** (`persona` + `organization`); it never edits `conversation_planner.json`.
