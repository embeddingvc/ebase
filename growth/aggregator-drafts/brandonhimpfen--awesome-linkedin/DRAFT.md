# Draft: brandonhimpfen/awesome-linkedin

- Target repo: https://github.com/brandonhimpfen/awesome-linkedin
- Category: LinkedIn outreach
- Status: draft prepared, AWAITING HUMAN APPROVAL — not submitted
- Action type: direct PR ("Contributions are welcome... follow CONTRIBUTING.md, including
  formatting, scope alignment, and category placement.")
- Contribution guidelines: `CONTRIBUTING.md` at repo root (referenced but full text not fetched
  in this pass — confirm exact rules before opening the PR)
- Note: small/low-traffic list (~4 stars) but exact category fit ("Recruitment & Talent
  Solutions" section exists) — low referral volume, low submission risk/effort.

## Placement

Section: `## Recruitment & Talent Solutions`

Current neighbors:
- `[HireEZ](https://hireez.com/) – AI-powered recruitment tool with LinkedIn sourcing
  integration.`
- `[PhantomBuster LinkedIn Automations](https://phantombuster.com/phantoms/linkedin) – Automate
  LinkedIn outreach and data scraping.`

"ebase" sorts alphabetically between "HireEZ" and "PhantomBuster".

Entry format used in this section:
```
- [Name](URL) – Brief description.
```
(Note: this list uses an en dash "–" as separator, not a hyphen.)

## Proposed diff (illustrative — confirm exact surrounding lines against the live file before
opening the PR)

```diff
 - [HireEZ](https://hireez.com/) – AI-powered recruitment tool with LinkedIn sourcing integration.
+- [ebase](https://github.com/embeddingvc/ebase) – Open-source (MIT) LinkedIn recruiting outreach for Claude Code, with a purpose-built MCP server, personalized messaging workflows, and enforced daily activity limits.
 - [PhantomBuster LinkedIn Automations](https://phantombuster.com/phantoms/linkedin) – Automate LinkedIn outreach and data scraping.
```

## PR title
`Add ebase to Recruitment & Talent Solutions`

## PR description (draft)

> Adds **ebase** (https://github.com/embeddingvc/ebase) to Recruitment & Talent Solutions.
>
> ebase is a free, open-source (MIT) tool that runs LinkedIn recruiting outreach from inside
> Claude Code: a purpose-built MCP server (not generic "computer use") drives the user's own
> signed-in Chrome to send connection requests, DMs, and plan follow-ups, with daily activity
> caps enforced in software (25 connection requests / 50 DMs / 100 profile views per day) and
> persistent per-user pipeline state.
>
> **Disclosure:** I'm a maintainer of ebase, submitting this per your CONTRIBUTING.md. Happy to
> adjust wording/placement or withdraw if it's not a fit.

## Compliance checklist
- [x] Affiliation disclosed in PR description
- [x] No blocked claims used
- [x] Factual description matches current README (main branch)
- [x] No fake endorsements, star exchange, or reciprocal promotion
- [x] Matches existing entry format (en dash separator)
- [ ] Full `CONTRIBUTING.md` text not yet fetched — re-verify format/length rules before
      submission.
- [ ] NOT YET SUBMITTED — no fork created, no PR opened. Requires explicit approval.
