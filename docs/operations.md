# Operations: env vars, data layout, Make targets

## Environment variables

- **LinkedIn browser**
  - `CDP_URL` (default `http://localhost:9222`)
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
  - `logs/server.log` (MCP server logger)
  - `logs/cron.log` (cron scheduler)

## Useful Make targets

Run `make help` to see all targets. Common ones:

- `make install`: install deps + Playwright chromium
- `make browser`: start Chrome with CDP enabled
- `make cron`: start the cron scheduler server in the foreground
- `make stop-cron`: stop the cron scheduler server
- `make status`: check if Chrome and cron are running
- `make test`: run the test suite (delegates to `make -C testing test`)
- `make test_conversation`: run conversation-planner tests (needs `ANTHROPIC_API_KEY`)
- `make sync-version`: copy `VERSION` into `pyproject.toml`
- `make check-version`: CI gate — assert `VERSION` and `pyproject.toml` match
- `make check-repo-url`: verify `install.sh`, `README.md`, and `CONTRIBUTING.md` use the same repo org/name
- `make -C testing web`: start the dev dashboard (see [`testing/README.md`](../testing/README.md))
