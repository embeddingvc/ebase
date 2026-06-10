---
name: setup-outreach
description: >-
  Interactive setup wizard: scrape the signed-in LinkedIn profile for a draft
  operator config, present it for review, iterate on corrections, then persist
  via merge_conversation_planner_identity. Also covers browser/CDP prep and
  optional campaign tuning. Use for first-run onboarding, /setup-outreach, or
  configuring persona.json.
---

# Setup Outreach (interactive wizard)

Guide the operator **one step at a time**. Do **not** run the full wizard in a single turn — finish the current sub-step, then **stop and wait** for the user.

**Filesystem rule:** Never read or write `outreach/config/` via raw paths or shell. Use MCP **`get_conversation_planner_config`**, **`get_style_example_prompts`**, **`merge_conversation_planner_identity`**, and **`upsert_conversation_planner_config`** only.

**Profile rule:** Step 2 always follows **scrape → present → refine → sync**. Do not call **`merge_conversation_planner_identity`** until the operator approves the final draft.

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

Call **`get_conversation_planner_config`**. If `persona.name` is still **"Nova Chen"**, treat identity as unset.

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

Mark 2a done. Proceed to 2b in the **same turn** only to present; do **not** sync yet.

### 2b — Present draft

Show the operator:

1. **Plain-language summary** — who the planner will say they are (name, role, org, angle).
2. **Draft JSON** — `persona` and `organization` objects exactly as you would persist them.
3. **Inferred vs scraped** — call out anything you guessed from headline or posts.

Ask: *"What would you like to change?"* (tone, role wording, org description, specialization emphasis, etc.)

Stop and wait. Do not sync.

### 2c — Corrections & adjustments

Apply the operator's edits to the draft. After each round:

1. Echo the **revised draft** (summary + JSON).
2. Ask whether they want **more changes** or are **ready to save**.

Repeat 2c until the operator explicitly says they are done (e.g. "looks good", "save it", "finalize").

**Optional deep refresh:** If the operator asks for richer LinkedIn signal (experience, education, skills), run **`parse_profile`** and fold that into the draft — then return to **2b** (present again) before any sync. Do not use **`parse_profile`** by default; **`scrape_profile`** is the initial source.

### 2d — Finalize & sync

1. Show the **final** draft one last time.
2. Require explicit confirmation to persist.
3. Call **`merge_conversation_planner_identity`**:
   - `persona_json` — JSON string with `name`, `role`, `organization`, `specialization`
   - `organization_json` — JSON string with `description`
4. Verify with **`get_conversation_planner_config`** and confirm `ok: true` from the merge response.
5. Summarize what was saved in plain language.

Stop and wait before step 3 (or step 4 if profile-only).

---

## Step 3 — Campaign, tone & style examples (optional)

Read **`get_conversation_planner_config`**. Show `campaign`,
`message_rules.tone`, `message_rules.tone_guidelines`, and
`message_rules.style_examples` (count + first reply preview).

Use **`AskQuestion`**: **Keep defaults** | **Customize** | **Skip**.

If customizing, run **3a** first. **Stop and wait** before any questionnaire.

After 3a (or if the operator skips campaign edits), use **`AskQuestion`**:

| Option | Action |
|--------|--------|
| **Yes — run questionnaires** | Continue to **3b → 3c** |
| **No — skip questionnaires** | Persist campaign changes only (if any), then jump to step 4 |

Do **not** call **`get_style_example_prompts`** or start tone/style questions
until the operator explicitly chooses **Yes**.

Each sub-step echoes a draft, collects approval, then persists with
**`upsert_conversation_planner_config`** (full planner JSON minus
`persona` / `organization`). Verify with **`get_conversation_planner_config`**
after every write.

### 3a — Campaign (goal / topic / value proposition)

Collect (one or two fields per turn): `campaign.goal`, `campaign.topic`,
`campaign.value_proposition`. Echo draft → approval → write.

**Stop and wait.** Ask yes/no before questionnaires (see gate above).

### 3b — Tone questionnaire

Only after the operator opts in. Call **`get_style_example_prompts`** and parse
`tone_questions[]`.

Walk the operator through **each** tone question **one at a time** (stop and
wait between questions). Show the `question` text and, when present, the
`example` as a hint. The operator may skip any question by saying *skip*.

After all answers (or skips), synthesize:

| Output field | Source |
|--------------|--------|
| `message_rules.tone` | Answer to the question whose `maps_to` is `message_rules.tone` (typically `tone_adjectives`). Keep ≤ ~80 chars. |
| `message_rules.tone_guidelines` | Join the other tone answers into one plain-text sentence (semicolon-separated prose). Use `""` when none were answered. |

Echo the draft `tone` + `tone_guidelines` → approval → include in the planner
payload for **`upsert_conversation_planner_config`**.

### 3c — Style example questionnaire

Only after **3b** (same opt-in). Use the same **`get_style_example_prompts`**
response. Parse
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
array. When all prompts are done, merge into the full planner config and call
**`upsert_conversation_planner_config`**.

Target **at least 2** non-skipped examples before finishing 3c; if the
operator skipped most scenarios, offer to revisit skipped ones or add a custom
example.

Validation rules to mirror in your draft (server-enforced):

- `message_rules.style_examples` must be a JSON array of objects.
- Each object must have a non-empty string `reply`.
- `label`, `context`, `incoming` are optional strings (or omitted entirely).
- `tone_guidelines` must be a string (use `""` for blank).

Stop and wait before step 4.

---

## Step 4 — Ready

1. **`get_conversation_planner_config`** — summary table:
   - Identity: `persona.name`, `persona.role`, `persona.organization`.
   - Campaign: `campaign.topic`, `campaign.goal`.
   - Voice: `message_rules.tone`, count of `message_rules.style_examples` (and
     a one-line preview of the first example's `reply`).
2. Close with **"You're ready!"** and next steps:
   - `connect to <linkedin-url>` (**`send-connection-request`**)
   - **`conversation-planner`** for a prospect

Mark all checklist items done.

---

## Troubleshooting

| Symptom | Guidance |
|---------|----------|
| CDP connection refused | `make browser`; port 9222 |
| Scrape returns login page | Sign in in installer Chrome profile |
| Draft feels wrong / too generic | Iterate in 2c; optional **`parse_profile`** refresh |
| Still "Nova Chen" after sync | 2d merge failed — check tool response, retry |
| MCP tools missing | `./install.sh` or `make claude-install` — `docs/install.md` |

---

## Related tools

| Tool | Role |
|------|------|
| **`scrape_profile`** | Initial draft + session check |
| **`parse_profile`** | Optional deep refresh when scrape is too thin |
| **`merge_conversation_planner_identity`** | Persist approved persona.json |
| **`get_conversation_planner_config`** | Read merged config (persona + planner) |
| **`get_style_example_prompts`** | Tone + style-example questionnaire (steps 3b–3c) |
| **`upsert_conversation_planner_config`** | Campaign + tone + style examples (step 3); writes the full planner JSON minus persona/organization |

For a standalone LinkedIn-only identity refresh (no wizard), use **`sync-planner-persona-from-linkedin`** (`parse_profile`-first).

Do **not** run outreach skills during setup unless the user asks after step 4.
