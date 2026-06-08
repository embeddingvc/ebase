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

**Filesystem rule:** Never read or write `outreach/config/` via raw paths or shell. Use MCP **`get_conversation_planner_config`**, **`merge_conversation_planner_identity`**, and **`upsert_conversation_planner_config`** only.

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
- [ ] 3. Campaign & tone (optional)
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
| **Campaign only** | Persona saved; jump to step 3 |
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

## Step 3 — Campaign & tone (optional)

Read **`get_conversation_planner_config`**. Show `campaign` and `message_rules.tone`.

Use **`AskQuestion`**: **Keep defaults** | **Customize** | **Skip**

If customizing, collect goal, topic, value proposition, and tone (one or two fields per turn). Echo draft → approval → **`upsert_conversation_planner_config`** (full planner JSON minus persona/organization) → verify.

Stop and wait before step 4.

---

## Step 4 — Ready

1. **`get_conversation_planner_config`** — summary table (name, role/org, campaign topic, tone).
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
| **`get_conversation_planner_config`** | Read merged config |
| **`upsert_conversation_planner_config`** | Campaign / rules (step 3) |

For a standalone LinkedIn-only identity refresh (no wizard), use **`sync-planner-persona-from-linkedin`** (`parse_profile`-first).

Do **not** run outreach skills during setup unless the user asks after step 4.
