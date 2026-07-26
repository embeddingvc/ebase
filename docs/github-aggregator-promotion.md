# GitHub Aggregator Promotion Strategy

Repository: https://github.com/embeddingvc/ebase

## Purpose

Earn accurate, contributor-compliant listings for ebase in relevant GitHub
aggregator repositories (awesome-lists, tool directories, MCP/agent catalogs)
to increase qualified discovery and installs. This is a research-and-draft
workflow — no public write (issue, PR, comment, fork) happens without explicit
human approval from Ruoqi.

## Canonical positioning

Default short description:

> ebase — Open-source LinkedIn recruiting outreach for Claude Code, with
> purpose-built MCP tools, personalized messaging workflows, follow-up
> automation, persistent pipeline state, and enforced daily activity limits.

Use shorter wording when a target's format requires it, but preserve factual
meaning. Always disclose contributor affiliation with ebase. Always link the
canonical repo URL above.

### Blocked claims

Never use, in any draft or listing text:

- "undetectable"
- "guaranteed safe"
- "officially approved by LinkedIn"
- "guaranteed replies"
- "guaranteed hires"

Prefer "enforced daily activity limits" over any claim that the tool cannot be
flagged.

## Qualification criteria for a target repository

- Category fit: Claude Code, MCP, AI agents, recruiting technology, LinkedIn
  outreach, browser automation, self-hosted automation, open-source
  alternatives to Dripify/Expandi/Octopus/Linked Helper.
- Actively maintained (recent commits/merges, not an abandoned list).
- Contribution rules are readable and don't prohibit self-submission or
  automation-built tools.
- Comparable entries already exist (proof the category accepts similar tools).
- Not a scraped spam directory or paid-only placement service.

## Messaging guardrails

- Never impersonate an unaffiliated user — every draft discloses the
  contributor's affiliation with ebase.
- No fake endorsements, star exchanges, reciprocal-promotion schemes,
  duplicate identities, or mass mentions.
- Follow each target repo's `CONTRIBUTING.md`, issue/PR templates, ordering,
  punctuation, description length, and category rules exactly.
- Quality and category fit over volume — do not optimize for submission count.

## Success metrics

- Merge rate: qualified drafts submitted → accepted/merged.
- Referral traffic: `utm_content`-tagged visits and attributed stars/installs
  per merged listing.
- Setup completions attributable to aggregator referral, where traceable.
- Time-to-response and time-to-merge per target.

## Kill gates

Reconsider (narrow targeting, revise positioning, or pause) a category or the
whole effort when:

- Rejection rate for a category exceeds acceptance over a rolling month.
- A merged listing produces no measurable referral traffic after 60 days.
- A maintainer asks to stop or flags the submission as unwanted — never send
  a second follow-up after rejection or a stop request, for that repo.
- Effort spent drafting materially exceeds the referral value produced,
  per the monthly strategy review.

## Human approval workflow

1. Claude runs discovery/drafting/review on schedule and updates
   `growth/aggregator-targets.csv` plus a dated report under
   `growth/aggregator-runs/`.
2. Each report ends with an **approval queue**: one entry per proposed public
   action (exact repo, action, proposed text/diff, affiliation disclosure).
3. Ruoqi reviews and marks each item Approve / Revise / Reject.
4. Only an explicitly approved action is executed, via a separate follow-up
   prompt naming that one action. The execution step records the resulting
   issue/PR URL and timestamp back into the tracker.
5. No merges, no unattended public writes, ever — same bottleneck model as
   the rest of this repo's SDLC (see `CLAUDE.md`).
