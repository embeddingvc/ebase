# Operations: env vars, data layout, Make targets

## Environment variables

- **LinkedIn browser / worker**
  - `CDP_URL` (default `http://localhost:9222`)
  - `POLL_INTERVAL` (seconds, default `5`)
- **Planner (Anthropic API mode)**
  - `ANTHROPIC_API_KEY` (required to call the API)
  - `CLAUDE_MODEL` (default `claude-haiku-4-5-20251001`)

Example: copy `.env.example` to `.env` and fill your values (never commit `.env`).

See also [`docs/web-dashboard.md`](./web-dashboard.md#environment-variables) for dashboard-specific variables (`WEB_HOST`, `WEB_PORT`, `OUTREACH_MOCK`, `OUTREACH_DATA_ROOT`, `CLAUDE_WEB_TIMEOUT_SEC`, …).

## Operational data layout

- **Queue automation**
  - `outreach/queue/pending.json`: input queue (worker pops ready jobs)
  - `outreach/queue/completed.json`: successes
  - `outreach/queue/failed.json`: failures
- **Pipeline records**
  - `outreach/prospects/<prospect_id>.json`
  - `outreach/conversations/<prospect_id>.json`
  - `outreach/connections.json` (upserted via MCP `save_connection`)
- **Audit logs**
  - `outreach/logs/actions.jsonl`
  - `outreach/logs/planned_messages.jsonl`
- **Reports**
  - `outreach/storage/reports/<prospect_id>.md`
- **Process logs**
  - `outreach/logs/worker.log` (stdout/stderr stream from `make server`)
  - `logs/server.log` (MCP server logger)
  - `logs/worker.log` (worker logger)

## Useful Make targets

Run `make help` to see all targets. Common ones:

- `make install`: install deps + Playwright chromium
- `make browser`: start Chrome with CDP enabled
- `make run`: start Chrome + worker
- `make server`: start worker only (Chrome must already be running)
- `make status`: check if Chrome/worker are running
- `make queue`: pretty-print pending/completed/failed queue JSON
- `make logs`: tail `outreach/logs/worker.log`
- `make test`: run exploration tests
- `make test_conversation`: run conversation-planner tests (needs `ANTHROPIC_API_KEY`)
- `make web`: start the dashboard in the foreground
- `make stop-web`: stop the dashboard
