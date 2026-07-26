---
name: aggregator-discovery
description: Run a GitHub aggregator-promotion pass for ebase (discovery + drafting + review) and persist the results with a real, working git push. Use when the user says "run aggregator discovery", "/aggregator-discovery", or asks to refresh the aggregator-promotion tracker. Exists because the cloud-routine version of this workflow cannot push (GitHub App lacks write access) — this skill runs in a local session with the user's own git credentials instead.
---

# Aggregator discovery (local)

Repo-local skill, not synced to end-user installs (lives under `.claude/skills/`,
outside `outreach/skills/`) — this is Ruoqi's own growth-ops tooling for
promoting ebase, not something to ship to people who install ebase.

Read `docs/github-aggregator-promotion.md` and `growth/aggregator-config.yaml`
first — they are the source of truth for strategy, qualification criteria,
blocked claims, and weekly limits. Do not duplicate that content here; if it
drifts from this skill, the docs win.

## Non-negotiable rules (same as the docs)

1. Research and drafting happen automatically. **No public write** (issue, PR,
   fork, comment, third-party form submission) happens without Ruoqi
   explicitly approving that exact item first.
2. Every draft discloses ebase affiliation. No fake endorsements, star
   exchanges, duplicate identities, or mass mentions.
3. Never use a phrase from `blocked_claims` in `growth/aggregator-config.yaml`.
4. Follow each target's own CONTRIBUTING/issue/PR rules exactly.

## Steps

### 1. Get on the state branch

```bash
git status   # stash/report anything uncommitted before switching, don't clobber it
git fetch origin growth/aggregator-state
git checkout growth/aggregator-state && git pull origin growth/aggregator-state
```

Remember the branch you started on — you'll switch back at the end.

### 2. Read state

- `docs/github-aggregator-promotion.md`, `growth/aggregator-config.yaml`,
  `growth/aggregator-targets.csv`
- Latest reports in `growth/aggregator-runs/` (don't repeat discovery/drafting
  already recorded there)
- Existing drafts in `growth/aggregator-drafts/`
- Current README and CHANGELOG on `main` (`git show main:README.md`) so every
  claim in a draft stays factual

### 3. Do the combined-mode work

Same scope as a scheduled run — discovery, drafting, review — bounded by the
limits in `growth/aggregator-config.yaml` (`max_new_candidates_per_run`,
`max_qualified_targets_per_week`, `max_submission_drafts_per_week`,
`minimum_days_before_follow_up`). Skip anything already qualified, excluded,
or drafted in the tracker.

- **Discovery:** search `preferred_categories`, qualify against the criteria
  in the doc, update `growth/aggregator-targets.csv` (append/update rows,
  never delete history).
- **Drafting:** for qualified high-priority targets with no open
  draft/issue/PR/merge/rejection, fetch the live README/CONTRIBUTING, write
  the smallest compliant change under
  `growth/aggregator-drafts/<owner>--<repo>/DRAFT.md`.
- **Review:** check any tracked open issue/PR URLs for responses, merges, or
  closures; follow up only past `minimum_days_before_follow_up` and never
  after a rejection or stop request.

### 4. Write the run report

`growth/aggregator-runs/YYYY-MM-DD-combined.md` — executive summary, work
completed, new/changed targets, drafts prepared, metrics/gate status,
risks/blocked work, next actions, and end with an **APPROVAL QUEUE**: one
entry per proposed public action (exact repo, action, proposed text/diff,
affiliation disclosure, Approve/Revise/Reject). If there's nothing worth
proposing, say so — don't manufacture work.

### 5. Commit and push (this is the step the cloud routine can't do)

```bash
git add growth/
git commit -m "Aggregator run YYYY-MM-DD: <one-line summary>"
git push origin growth/aggregator-state
```

Use `origin` (the user's fork, `huangruoqi/ebase`) unless the user has said
otherwise — pushing to `upstream` (`embeddingvc/ebase`) is also fine since
Ruoqi has direct write access there, but don't push to `main` on either.

### 6. Return and report

```bash
git checkout <branch you started on>
```

Show the run report's executive summary and the full approval queue in the
chat response — that's the only way the results actually reach Ruoqi.
