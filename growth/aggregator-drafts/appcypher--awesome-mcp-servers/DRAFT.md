# Draft: appcypher/awesome-mcp-servers

- Target repo: https://github.com/appcypher/awesome-mcp-servers
- Category: MCP
- Status: draft prepared, AWAITING HUMAN APPROVAL — not submitted
- Action type: direct PR (community additions explicitly welcomed; README asks contributors to
  read `CONTRIBUTING.md`, no PR-blocking restriction found)
- Contribution guidelines: `CONTRIBUTING.md` at repo root (license is CC0; no anti-self-promotion
  clause found in README or footer)

## Placement

Section: `## ⚙️ Workflow Automation` (anchor `#workflow-automation`)

Current entries, in order:
1. Make
2. Taskade MCP

"ebase" sorts alphabetically before "Make", so it is inserted as the **first** entry in the
section, immediately after the section heading and before the "Make" line.

Entry format used throughout the file:
```
- <img src="[icon-url]" height="14"/> [ServerName](github-url) - Description text
```
Not every entry uses the `<img>` prefix (icon is optional/best-effort); a plain-text entry
without an icon is consistent with many existing rows, so the proposed diff omits it rather than
fabricate an icon URL.

## Proposed diff (unified, illustrative — confirm exact surrounding lines against the live file
before opening the PR, since the file may have changed since this draft was prepared)

```diff
 ## ⚙️ <a name="workflow-automation"></a>Workflow Automation

+- [ebase](https://github.com/embeddingvc/ebase) - Open-source MCP server for LinkedIn recruiting outreach: connection requests, DMs, and profile research via Playwright-driven Claude Code skills, with enforced daily activity limits and persistent pipeline state.
 - [Make](...) - ...
 - [Taskade MCP](...) - ...
```

## PR title
`Add ebase to Workflow Automation`

## PR description (draft)

> Adds **ebase** (https://github.com/embeddingvc/ebase) to the Workflow Automation section.
>
> ebase is an open-source (MIT) MCP server that wraps Playwright to drive LinkedIn recruiting
> outreach from Claude Code — connection requests, DMs, and profile research — with typed
> tool inputs/outputs, persistent per-user pipeline state, and enforced daily activity limits
> (25 connection requests / 50 DMs / 100 profile views per day).
>
> **Disclosure:** I'm a contributor/maintainer of ebase, submitting this listing per the repo's
> contribution guidelines. Happy to adjust wording, placement, or drop the entry if it's not a
> fit.

## Compliance checklist
- [x] Affiliation disclosed in PR description
- [x] No blocked claims used (checked against `growth/aggregator-config.yaml` blocked_claims list)
- [x] Factual description matches current README (main branch) — MIT license, Playwright-based
      MCP server, per-day caps of 25 connection requests / 50 DMs / 100 profile views
- [x] No fake endorsements, star exchange, or reciprocal promotion
- [x] Matches existing entry format (plain `- [Name](url) - description`)
- [ ] NOT YET SUBMITTED — no fork created, no PR opened. Requires explicit approval.
