# Draft: jeremylongshore/claude-code-plugins-plus-skills

- Target repo: https://github.com/jeremylongshore/claude-code-plugins-plus-skills
- Category: Claude Code (plugin/skill marketplace)
- Status: draft prepared, AWAITING HUMAN APPROVAL — not submitted
- Action type: **issue-first** (their own process requires it, even though PRs are welcomed —
  see below)
- Contribution guidelines: `.github/CONTRIBUTING.md`

## Why issue-first, not direct PR

This repo's process is a two-step gate: **"Before opening a PR, file a GitHub issue using the
plugin-submission template... Your PR must link it via `Closes #N` or `Refs #N`."** So even
though direct PRs are the eventual mechanism, the compliant "smallest first step" here is the
issue, not a PR.

## Scope note (important — read before approving)

Submitting here is **not** a small text-listing change like the awesome-list drafts in this
batch. Their marketplace requires an actual plugin package meeting their schema:
- `plugins/[category]/ebase/.claude-plugin/plugin.json` (name, version, description, author,
  repository, license, etc.)
- `SKILL.md` per skill with all 8 mandatory frontmatter fields
- `PRD.md` (+ `ADR.md`, `ONE-PAGER.md` depending on tier)
- Passing `scripts/validate-skills-schema.py --marketplace --verbose` at or above their
  marketplace score threshold
- Passing their full CI (17-job `ci-required` aggregate) and a `gitleaks` secret scan
- A registered `.claude-plugin/marketplace.extended.json` entry

That packaging work is a separate, larger engineering task than the listing PRs in this batch —
flagging it explicitly rather than quietly scoping it down. This draft only prepares the
**pre-submission issue** (problem / users / success criteria), which is the compliant first move
and doesn't commit to the packaging work. If the issue is approved and filed, and a maintainer
response is encouraging, the packaging PR would need its own follow-up review and approval before
any code is written or submitted.

Their rules also state: **"No self-promotion or undisclosed third-party tools. Plugins for tools
you don't maintain should be transparently disclosed."** ebase is a tool we maintain, so this is
satisfied by the affiliation disclosure below (not a self-promotion ban).

## Proposed issue (using the plugin-submission template fields)

**Title:** `Plugin submission: ebase — LinkedIn recruiting outreach skills for Claude Code`

**Problem:** Recruiters and sourcers using Claude Code have no purpose-built way to run LinkedIn
outreach (connection requests, DMs, follow-ups) from inside their agent workflow without either
hand-rolling MCP tools or resorting to screenshot-based "computer use" automation that's slow and
fragile.

**Users:** Recruiters, talent partners, and founders doing their own candidate sourcing who want
LinkedIn outreach driven by Claude Code skills instead of a separate SaaS dashboard.

**Success criteria:** A `plugins/recruiting/ebase/` (or similar category) entry exposing ebase's
existing Claude skills (`/send-connection-request`, `/sync-pending-connection`,
`/conversation-planner`, `/setup-outreach`, `/reply-to-post`) that passes marketplace validation
and CI, with clear docs on required setup (macOS, Chrome CDP, LinkedIn login) since this plugin
drives a real browser session rather than being purely API-based.

**Disclosure:** I'm a maintainer of ebase (https://github.com/embeddingvc/ebase, MIT licensed),
filing this issue per your pre-submission process ahead of any PR.

## Compliance checklist
- [x] Affiliation disclosed in the issue text
- [x] No blocked claims used
- [x] Factual description matches current README/skills docs (5 skills, MIT, macOS + Chrome CDP
      requirement stated up front rather than glossed over)
- [x] No fake endorsements, star exchange, or reciprocal promotion
- [x] Packaging/engineering scope flagged explicitly rather than hidden
- [ ] NOT YET SUBMITTED — no issue filed, no PR opened, no fork created. Requires explicit
      approval, and packaging work requires a *separate* follow-up approval if the issue is
      well-received.
