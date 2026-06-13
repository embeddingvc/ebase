# Operations: env vars, data layout, Make targets

## Environment variables

- **LinkedIn browser / worker**
  - `CDP_URL` (default `http://localhost:9222`)
  - `POLL_INTERVAL` (seconds, default `5`)
- **Planner (Anthropic API mode)**
  - `ANTHROPIC_API_KEY` (required to call the API)
  - `CLAUDE_MODEL` (default `claude-haiku-4-5-20251001`)

Example: copy `.env.example` to `.env` and fill your values (never commit `.env`).

- **Cron scheduler server**
  - `WEB_HOST` / `WEB_PORT` (default `127.0.0.1:3847`) — bind address for `cron/server.py`
  - `OUTREACH_DATA_ROOT` — override the live `outreach/` data root (mostly for tests)
  - `CLAUDE_WEB_TIMEOUT_SEC` — timeout for scheduler-invoked Claude skill runs

Mock mode (`OUTREACH_MOCK`) and the dev dashboard are `testing/` concerns; see [`testing/docs/web-dashboard.md`](../testing/docs/web-dashboard.md).

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
- `make test`: run the test suite (delegates to `make -C testing test`)
- `make test_conversation`: run conversation-planner tests (needs `ANTHROPIC_API_KEY`)
- `make cron`: start the cron scheduler server in the foreground
- `make stop-cron`: stop the cron scheduler server
- `make -C testing web`: start the dev dashboard (see [`testing/README.md`](../testing/README.md))
