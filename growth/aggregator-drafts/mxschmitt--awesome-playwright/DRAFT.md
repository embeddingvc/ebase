# Draft: mxschmitt/awesome-playwright

- Target repo: https://github.com/mxschmitt/awesome-playwright
- Category: Browser automation
- Status: draft prepared, AWAITING HUMAN APPROVAL — not submitted
- Action type: direct PR ("Contributions welcome! Read the contribution guidelines first.")
- Contribution guidelines: `CONTRIBUTING.md` at repo root (not fully fetchable in this pass —
  confirm formatting/description-length rules against the live file before opening the PR)

## Placement

Section: `## Scraping & Automation`

Current neighbors:
- `[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) - Stealth Chromium with source-level
  fingerprint patches...`
- `[Human Browser](https://humanbrowser.cloud) - Playwright drop-in that runs scripts...`

"ebase" sorts alphabetically between "CloakBrowser" and "Human Browser".

Entry format used in this section:
```
- [Project Name](link) - Brief description.
```

## Proposed diff (illustrative — confirm exact surrounding lines against the live file before
opening the PR)

```diff
 - [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) - Stealth Chromium with source-level fingerprint patches...
+- [ebase](https://github.com/embeddingvc/ebase) - Open-source LinkedIn recruiting outreach that drives your real, signed-in Chrome over Playwright/CDP — connection requests, DMs, and profile research from Claude Code, with enforced daily activity limits.
 - [Human Browser](https://humanbrowser.cloud) - Playwright drop-in that runs scripts...
```

## PR title
`Add ebase to Scraping & Automation`

## PR description (draft)

> Adds **ebase** (https://github.com/embeddingvc/ebase) — an open-source (MIT) LinkedIn
> recruiting outreach tool for Claude Code. It's built on Playwright: a purpose-built MCP server
> attaches to the user's real, signed-in Chrome over CDP (not headless, not a bot account) to run
> structured LinkedIn operations — connection requests, DMs, profile scrapes — with typed inputs
> and JSON outputs instead of screenshot-based "computer use."
>
> **Disclosure:** I'm a maintainer of ebase, submitting per your contribution guidelines. Happy
> to adjust the description or placement, or drop it if it's not a fit for this list.

## Compliance checklist
- [x] Affiliation disclosed in PR description
- [x] No blocked claims used
- [x] Factual description matches current README (main branch) — Playwright/CDP-driven,
      real signed-in Chrome session, not headless, enforced daily caps
- [x] No fake endorsements, star exchange, or reciprocal promotion
- [x] Matches existing entry format
- [ ] Full `CONTRIBUTING.md` text not yet fetched — re-verify format/length rules before
      submission; this draft used only the README's brief pointer to that file.
- [ ] NOT YET SUBMITTED — no fork created, no PR opened. Requires explicit approval.
