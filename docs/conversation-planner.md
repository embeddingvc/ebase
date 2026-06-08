# Runtime conversation planner config

The `conversation-planner` skill supports live runtime configuration from two files (the MCP tool **`get_conversation_planner_config`** returns them merged as one JSON):

- `outreach/config/conversation_planner.json` — campaign, end goals, message rules, router (tracked in git)
- `outreach/config/persona.json` — operator `persona` and `organization` (gitignored; copy from `outreach/config/persona.json.example`)

`conversation_planner.json` controls:

- campaign goal + topic (`campaign`)
- preferred conversation end outcomes (`conversation_end_goals`)
- message limits/rules (`message_rules`)
- routing (`router`)

`persona.json` controls:

- outreach persona/profile (`persona`) and org framing (`organization`)

## Why this matters

You can change planner behavior (for example profile identity, end-state intent, or outreach topic) **without** restarting the MCP server and **without** reloading the skill.

## First-time setup

Run the **`setup-outreach`** skill in Claude Code (`/setup-outreach`). It **`scrape_profile`**s your signed-in LinkedIn profile, presents a draft **`persona`** + **`organization`**, walks you through corrections, then calls **`merge_conversation_planner_identity`** to write **`persona.json`**. See [Claude skills — setup-outreach](./skills.md#setup-outreach-first-run-wizard).

## Update methods

You can update config in either way:

1. Edit `outreach/config/conversation_planner.json` and/or `outreach/config/persona.json` directly (create `persona.json` from `persona.json.example` if you do not have one).
2. Use MCP tools (often via a skill):
   - `get_conversation_planner_config` — merged view of both files
   - `upsert_conversation_planner_config` — replace **`conversation_planner.json` only** (payload must not include `persona` / `organization`)
   - `merge_conversation_planner_identity` — shallow-merge LLM-authored `persona` / `organization` into **`persona.json`**
3. Re-run **`setup-outreach`** to refresh persona from LinkedIn with review, or use **`sync-planner-persona-from-linkedin`** for a **`parse_profile`**-first deep refresh (experience, education, skills) without the wizard.

Reads/writes are runtime-safe. Config is read from disk fresh on each MCP call.

## Example adjustments

- Switch outreach topic from startup recruiting to enterprise AI advisory by changing:
  - `campaign.topic`
  - `campaign.goal`
- Prefer scheduling calls over collecting resumes by reordering/rewriting:
  - `conversation_end_goals.preferred`
- Customize terminal reason codes for your pipeline with custom `ended_reason` IDs (conversation schema now allows non-empty custom strings).
