---
name: ebase-setup
description: >-
  Interactive setup wizard: scrape the signed-in LinkedIn profile for a draft
  operator config, present it for review, iterate on corrections, then write
  it straight to persona.json and validate with tools/validate_outreach_config.py.
  Also covers browser/CDP prep and optional campaign tuning. Use for
  first-run onboarding, /ebase-setup, or configuring persona.json.
---

# Setup Outreach (interactive wizard)

Guide the operator **one step at a time**. Do **not** run the full wizard in a single turn — finish the current sub-step, then **stop and wait** for the user.

## Browser tool policy (strict — read first)

Every LinkedIn browser action in this wizard goes through the **LinkedIn MCP server** (tools
prefixed `mcp__linkedin__*`) and **only** that server. The LinkedIn MCP attaches to the
operator's logged-in Chrome over CDP on port `9222` with this project's rate-limits, human-like
jitter, and bot-detection safeguards — substituting any other browser surface defeats those
guarantees and can get the operator's LinkedIn account flagged at the very moment they are
first signing in.

Even if other browser tools are registered in the current Claude CLI session, do **not** use
them for this workflow:

- **No other browser MCPs.** Do not use `chrome-devtools`, `playwright`, `puppeteer`,
  `browser-use`, `browserbase`, `gstack` browser, or any other Chrome-attached MCP to open,
  click, type, or read on `linkedin.com` — including the `/in/me/` self-scrape.
- **No "Claude in Chrome" extension / Chrome side-panel** to drive the browser on `linkedin.com`.
- **No `WebFetch`, `WebSearch`, `curl`, `wget`, `fetch`, `requests`, or `Bash`** against
  `linkedin.com` / `licdn.com`.
- **No manual operator hand-off** for the scrape ("paste your headline here") — always call the
  LinkedIn MCP scrape tool first and only fall back to operator-supplied text if the tool errors.

Allowed browser-side tools in this skill (LinkedIn MCP only):

- `mcp__linkedin__scrape_profile` (default for the wizard self-scrape)
- `mcp__linkedin__parse_profile` (optional deep refresh in 2c)

The `make browser` step is the only shell command involved in browser setup, and it launches
the **operator's own Chrome** with CDP — it is not a substitute browser-automation tool.

If `mcp__linkedin__scrape_profile` / `parse_profile` are not registered in the current session
(step 1, 2a, or the optional 2c refresh), **stop and tell the operator the LinkedIn MCP is not
registered** (fix: run `./install.sh` or `make claude-install`, then start a **new** Claude Code
session — MCP servers only load at session start). Do **not** pick up a different browser tool
as a fallback. This does **not** block the rest of the wizard: steps 0, 2b–2d, 3, and 4 only
touch local config files and work whether or not the LinkedIn MCP has loaded yet (see below).

## System check (run first)

Before setup work, check service health and for a newer ebase version:

```bash
bin/outreach-update-check 2>/dev/null || true
```

Follow the inline flow in skill **`ebase-upgrade`** for every line printed:
`SERVICE_DOWN <service> <url>` (inform the user, non-blocking), then
`UPGRADE_AVAILABLE` (ask to upgrade), `UPGRADED`/`JUST_UPGRADED` (log and
continue), or `UP_TO_DATE`/empty (continue silently).
Do not block on network failures.

**Filesystem rule:** Read and write `outreach/config/persona.json`, `outreach/config/conversation_planner.json`,
and `outreach/config/style_example_prompts.json` **directly** with the Read / Write tools — no MCP round trip.
When the local file is absent, fall back to reading the matching bundled file
(`persona.json.example`, `conversation_planner.json.example`, or `style_example_prompts.json`
itself, which is bundled and always present). After writing a config file, confirm it before
telling the operator it saved:

```bash
uv run python tools/validate_outreach_config.py --persona outreach/config/persona.json --planner outreach/config/conversation_planner.json
```

(Pass only the flag for whichever file you just wrote.) On `error: ...`, fix the draft and
re-write — never leave an invalid file in place. This path has no LinkedIn MCP dependency, so it
works in the very first Claude Code session right after install, before the newly-registered
MCP server has loaded.

**Profile rule:** Step 2 always follows **scrape → present → refine → sync**. Do not write
`persona.json` until the operator approves the final draft.

---

## Progress tracker

```
Setup progress:
- [ ] 0. Welcome & path
- [ ] 1. Browser & LinkedIn session
- [ ] 2a. Scrape profile → draft config
- [ ] 2b. Present draft to operator
- [ ] 2c. Corrections & adjustments (repeat until done)
- [ ] 2d. Finalize & sync
- [ ] 3. Campaign, tone & style examples (optional)
- [ ] 4. Ready
```

---

## Step 0 — Welcome & choose path

Explain the flow: browser session → **scrape your profile → review & edit → save** → optional campaign → done.

Read **`outreach/config/persona.json`** (fall back to `persona.json.example`, then to
`{"persona": {"name": "Nova Chen"}}` if neither exists). If `persona.name` is still
**"Nova Chen"**, treat identity as unset.

**First-run check.** If identity is unset (still "Nova Chen"), this is likely a fresh install.
Check whether the LinkedIn MCP tools are registered in this session (look for
`mcp__linkedin__scrape_profile` in your available tools — don't call it yet, just check it's
listed). If it is **not** listed:

> This looks like your first time running setup, and the LinkedIn browser tools haven't loaded
> into this Claude Code session yet — that's expected right after install, since MCP servers
> only load at session start. Please **close this session and start a new one**, then run
> `/ebase-setup` again. 

Stop there — don't offer the path menu below until the tools are present, since Full setup and
Profile only both need step 1. If identity is unset but the tools **are** listed (e.g. this is a
second session), proceed normally.

Use **`AskQuestion`** (or ask in chat):

| Option | When |
|--------|------|
| **Full setup** | First time; steps 1 → 4 |
| **Profile only** | Browser works; start at 2a |
| **Campaign / tone only** | Persona saved; jump to step 3 |
| **Re-sync profile** | Re-run 2a → 2d from scratch |

Stop after the user picks a path.

---

## Step 1 — Browser & LinkedIn session

**Goal:** Live Chrome with CDP + signed-in LinkedIn.

```bash
make browser
```

Sign in at `https://www.linkedin.com` in **that** Chrome window (dedicated profile).

**Session check:** Call **`scrape_profile`** with `profile_url: "https://www.linkedin.com/in/me/"`.

| Result | Action |
|--------|--------|
| JSON with a real `name` | Session OK — mark step 1 done |
| CDP / connection error | `make browser`, port **9222** — retry when ready |
| Login error | Finish LinkedIn sign-in, then retry |
| Tool not found (`mcp__linkedin__scrape_profile` unavailable) | LinkedIn MCP hasn't loaded in this session — see browser tool policy above. Steps 0 / 2b–2d / 3 / 4 don't need it; only 1 / 2a / optional-2c do. |

Keep the scrape JSON in context for step 2a if continuing in the same session; otherwise re-scrape in 2a.

Stop and wait before step 2.

---

## Step 2 — Operator profile (persona.json)

Four sub-steps. **Never skip 2b or 2c** — the operator must see and approve the draft before sync.

### 2a — Scrape & draft

Call **`scrape_profile`** on `https://www.linkedin.com/in/me/` (reuse step 1 result only if still in the same conversation turn and the user has not asked to refresh).

From the scrape JSON, **you** synthesize a draft **`persona`** + **`organization`** (not a raw dump):

| Scrape field | Draft field | How to use |
|--------------|-------------|------------|
| `name` | `persona.name` | Use as-is when present |
| `title` | `persona.role`, `persona.organization` | Split headline (e.g. "Engineer at Acme" → role + org); if ambiguous, infer best-effort and mark as inferred |
| `about` | `persona.specialization`, `organization.description` | Short specialization (≤ ~500 chars) + longer org framing (≤ ~1200 chars); do not paste the full About verbatim unless the user wants that |
| `recent_posts` | (optional) | Thematic hints for specialization only — summarize, do not paste post bodies |
| `location` | (optional) | Brief mention in `organization.description` when relevant |

If scrape data is thin (empty `about`, generic `title`), say so honestly and draft shorter copy — offer to re-scrape or fill gaps in 2c.

Mark 2a done. Proceed to 2b in the **same turn** only to present; do **not** write `persona.json` yet.

### 2b — Present draft

Show the operator:

1. **Plain-language summary** — who the planner will say they are (name, role, org, angle).
2. **Draft JSON** — `persona` and `organization` objects exactly as you would persist them.
3. **Inferred vs scraped** — call out anything you guessed from headline or posts.

Ask: *"What would you like to change?"* (tone, role wording, org description, specialization emphasis, etc.)

Stop and wait. Do not write yet.

### 2c — Corrections & adjustments

Apply the operator's edits to the draft. After each round:

1. Echo the **revised draft** (summary + JSON).
2. Ask whether they want **more changes** or are **ready to save**.

Repeat 2c until the operator explicitly says they are done (e.g. "looks good", "save it", "finalize").

**Optional deep refresh:** If the operator asks for richer LinkedIn signal (experience, education, skills), run **`parse_profile`** and fold that into the draft — then return to **2b** (present again) before any write. Do not use **`parse_profile`** by default; **`scrape_profile`** is the initial source.

### 2d — Finalize & sync

1. Show the **final** draft one last time.
2. Require explicit confirmation to persist.
3. Read the current **`outreach/config/persona.json`** (fall back to `persona.json.example`, then the
   hardcoded default `{"persona": {"name": "Nova Chen", "role": "virtual team member",
   "organization": "Embedding VC", "specialization": "AI research and operations"},
   "organization": {"description": "We back early-stage AI startups and connect top talent with
   great AI companies."}}` if neither file exists). Shallow-merge the approved draft on top —
   only overwrite the `persona`/`organization` fields the operator approved (`name`, `role`,
   `organization`, `specialization`; `description`); leave any other existing field untouched.
4. Write the merged object to **`outreach/config/persona.json`**.
5. Validate: `uv run python tools/validate_outreach_config.py --persona outreach/config/persona.json`.
   On `error: ...`, fix the draft (you likely introduced an unknown key or a non-string value) and re-write.
6. Read the file back and confirm the fields match what you intended to save.
7. Summarize what was saved in plain language.

Stop and wait before step 3 (or step 4 if profile-only).

---

## Step 3 — Campaign, tone & style examples (optional)

Read **`outreach/config/conversation_planner.json`** (fall back to `conversation_planner.json.example`).
Show `campaign`, `message_rules.tone`, `message_rules.tone_guidelines`, and
`message_rules.style_examples` (count + first reply preview).

Use **`AskQuestion`**: **Keep defaults** | **Customize** | **Skip**.

If customizing, run **3a** first. **Stop and wait** before any questionnaire.

After 3a (or if the operator skips campaign edits), use **`AskQuestion`**:

| Option | Action |
|--------|--------|
| **Yes — run questionnaires** | Continue to **3b → 3c** |
| **No — skip questionnaires** | Persist campaign changes only (if any), then jump to step 4 |

Do **not** read `outreach/config/style_example_prompts.json` or start tone/style questions
until the operator explicitly chooses **Yes**.

Each sub-step echoes a draft, collects approval, then persists by writing the **full**
`conversation_planner.json` (merge the draft into the object you read at the top of step 3;
never drop `campaign`/`message_rules`/`router` fields you weren't asked to change) and running:

```bash
uv run python tools/validate_outreach_config.py --planner outreach/config/conversation_planner.json
```

Read the file back after every write to verify.

### 3a — Campaign (goal / topic / value proposition)

Collect (one or two fields per turn): `campaign.goal`, `campaign.topic`,
`campaign.value_proposition`. Echo draft → approval → write.

**Stop and wait.** Ask yes/no before questionnaires (see gate above).

### 3b — Tone questionnaire

Only after the operator opts in. Read **`outreach/config/style_example_prompts.json`** and parse
`tone_questions[]`.

Walk the operator through **each** tone question **one at a time** (stop and
wait between questions). Show the `question` text and, when present, the
`example` as a hint. The operator may skip any question by saying *skip*.

After all answers (or skips), synthesize:

| Output field | Source |
|--------------|--------|
| `message_rules.tone` | Answer to the question whose `maps_to` is `message_rules.tone` (typically `tone_adjectives`). Keep ≤ ~80 chars. |
| `message_rules.tone_guidelines` | Join the other tone answers into one plain-text sentence (semicolon-separated prose). Use `""` when none were answered. |

Echo the draft `tone` + `tone_guidelines` → approval → include in the merged
`conversation_planner.json` write.

### 3c — Style example questionnaire

Only after **3b** (same opt-in). Use the same `style_example_prompts.json`
contents. Parse
`style_example_prompts[]` — this is the **canonical outreach questionnaire**.

Walk through **every** prompt in array order, **one scenario per turn** (stop
and wait after each). For prompt index *i* of *N*, show:

1. Scenario label (`label` or `id`).
2. The `question` verbatim.
3. `incoming` when non-null — quote it as *"Prospect said: …"*.
4. `hint` when present.

Ask the operator to write **`reply`** — exactly how they would send it. They
may **skip** a scenario (leave `reply` empty for that entry).

Build each collected example from the prompt object:

| Field | Source |
|-------|--------|
| `reply` | Operator's answer (required to keep the example) |
| `label` | From prompt `label` |
| `context` | From prompt `context` |
| `incoming` | From prompt `incoming` when non-null |

Do **not** invent scenario text — copy `label`, `context`, and `incoming` from
the questionnaire entry.

After each reply (or explicit skip), echo the running `style_examples[]`
array. When all prompts are done, merge into the full planner config and
write + validate.

Target **at least 2** non-skipped examples before finishing 3c; if the
operator skipped most scenarios, offer to revisit skipped ones or add a custom
example.

Validation rules to mirror in your draft (checked by `tools/validate_outreach_config.py`):

- `message_rules.style_examples` must be a JSON array of objects.
- Each object must have a non-empty string `reply`.
- `label`, `context`, `incoming` are optional strings (or omitted entirely).
- `tone_guidelines` must be a string (use `""` for blank).

Stop and wait before step 4.

---

## Step 4 — Ready

1. Read **`outreach/config/persona.json`** and **`outreach/config/conversation_planner.json`** — summary table:
   - Identity: `persona.name`, `persona.role`, `persona.organization`.
   - Campaign: `campaign.topic`, `campaign.goal`.
   - Voice: `message_rules.tone`, count of `message_rules.style_examples` (and
     a one-line preview of the first example's `reply`).
2. Close with **"You're ready!"** and next steps:
   - `connect to <linkedin-url>` (**`ebase-send-connection-request`**)
   - **`ebase-conversation-planner`** for a prospect

Mark all checklist items done.

---

## Troubleshooting

| Symptom | Guidance |
|---------|----------|
| CDP connection refused | `make browser`; port 9222 |
| `make browser` itself fails (missing Chrome for Testing, command not found) | Tell the operator plainly what failed and point them at the repo's install docs / `./install.sh`; don't retry silently in a loop |
| Scrape returns login page | Sign in in installer Chrome profile |
| Draft feels wrong / too generic | Iterate in 2c; optional **`parse_profile`** refresh |
| Still "Nova Chen" after sync | Re-read `outreach/config/persona.json` — the write in 2d may have failed validation; check the `validate_outreach_config.py` output and retry |
| `persona.json` / `conversation_planner.json` exists but isn't valid JSON | Don't merge into it — show the operator the parse error, offer to start from the matching `*.example` file instead, and confirm before overwriting |
| `validate_outreach_config.py` reports `error: ...` | Fix the offending field in your draft (unknown key or non-string value) and re-write; never leave the file in an invalid state |
| `scrape_profile` / `parse_profile` tool not found | LinkedIn MCP hasn't loaded in this session — `./install.sh` or `make claude-install`, then start a **new** session. Only affects steps 1 / 2a / optional-2c; the rest of the wizard doesn't need it |
| Operator wants to stop mid-wizard | Note current progress-tracker state out loud so they know where a re-run of `/ebase-setup` will resume; don't force them through remaining steps |

---

## Related tools

| Tool | Role |
|------|------|
| **`scrape_profile`** (MCP) | Initial draft + session check |
| **`parse_profile`** (MCP) | Optional deep refresh when scrape is too thin |
| **`tools/validate_outreach_config.py`** (Bash) | Confirms `persona.json` / `conversation_planner.json` are well-formed after a direct write |
| **`ebase-upgrade`** (skill) | System check: service health + version check, optional git pull when `UPGRADE_AVAILABLE` (run at skill start) |

For a standalone LinkedIn-only identity refresh (no wizard), use **`ebase-sync-persona`** (`parse_profile`-first).

Do **not** run outreach skills during setup unless the user asks after step 4.
