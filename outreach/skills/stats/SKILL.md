---
name: stats
description: Show outreach performance — connection funnel, reply rates, sequence-step effectiveness, and conversion by goal. Use when the user asks "/stats", "show me outreach stats", "how is the campaign doing", or similar.
---

# Outreach Stats

Render a funnel dashboard from the `get_outreach_stats` MCP tool. One tool call, no loops — all aggregation happens server-side.

## Inputs

- `since` (optional) — `YYYY-MM-DD`. If the user gives a relative date ("last week", "since Monday"), resolve it to an absolute date before calling the tool.

## Steps

### 1. Call the MCP tool

```
Tool: get_outreach_stats
  since: <YYYY-MM-DD or omit>
```

Returns JSON: `pipeline`, `connections`, `replies`, `outcomes`, `sequence.by_step`, `by_end_goal`.

### 2. Render the dashboard

```
── Outreach Funnel ──────────────────────────────────────
  Connections sent:      {connections.sent}
  Accepted:              {connections.accepted}  ({connections.acceptance_rate_pct}%)
  Pending:               {connections.pending}
  Replied:               {replies.total_replied}  ({replies.reply_rate_pct}% of accepted)
  Converted:              {outcomes.total_converted}  ({outcomes.conversion_rate_pct}% of accepted)

── Pipeline Stages ──────────────────────────────────────
  <one line per pipeline.by_stage entry: "  {stage:<20} {count}">

── Sequence Step Reply Rates ────────────────────────────
  <one line per sequence.by_step entry, sorted by step: "  Step {n}   {sent} sent → {got_reply} replies  ({reply_rate_pct}%)">

── Outcomes ─────────────────────────────────────────────
  <one line per outcomes.by_ended_reason entry: "  {reason:<18} {count}">

── By Goal ──────────────────────────────────────────────
  <one line per by_end_goal entry: "  {goal:<18} {total} prospects  →  {converted} converted ({rate_pct}%)">
```

Omit any section whose backing data is empty (e.g. no `sequence.by_step` entries yet).

### 3. Add insight lines

After the dashboard, add 1-2 short insight lines derived from the numbers already returned — do not re-fetch data:

- Biggest funnel drop-off: the `sequence.by_step` entry with the lowest `reply_rate_pct` (only if 2+ steps have data).
- Best-converting goal: the `by_end_goal` entry with the highest `rate_pct` (only if 2+ goals have data).
- Acceptance rate below 50%: call it out if `connections.acceptance_rate_pct < 50`.

## Error Handling

- Tool returns `"error: ..."` — report it verbatim and stop.
- All counts are zero (no outreach data yet) — say so plainly instead of printing an empty dashboard.
