# Quickstart (live browser automation)

Day-to-day, the simplest flow is:

```bash
make run
```

That will:

- Start Chrome (if not already running) with a dedicated profile and CDP port.
- Start the worker in the foreground (`make server`).

Then log into LinkedIn in the Chrome window (first time per profile) and use either:

- **Claude CLI** (recommended for installation)
  - `make claude-install` — default: `--scope user` MCP + sync skills to `~/.claude/skills`
  - `make claude-install LOCAL=1` — `--scope local` MCP only; skills stay under `outreach/skills/` in the repo
- **Claude + MCP tools**
- **Queue files + worker** (recommended for batch automation)

## Live mode checklist

1. Start Chrome with debugging (from the repo root):

   ```bash
   make browser
   ```

2. Sign in to LinkedIn in that Chrome window.

3. Use Claude with the MCP tools as usual.

If Chrome is not running with remote debugging, live tools will fail until `make browser` (or an equivalent launch) is used.

## Example usage

0. Run the **setup-outreach** skill to configure your operator profile (or sync planner persona from LinkedIn).
1. Connect to `<linkedin-url>`.
2. Is `<linkedin-url>` my connection?
3. Add `Run conversation planner skill` as a scheduled task.

## Mock mode (optional, no browser)

For scripted tests without a browser, `tools/server.py` can run in mock mode when `_mock_mcp_enabled()` returns `True` (see `tools/server.py`). In mock mode, tools use `tools/mock.py` instead of Playwright.

**Note:** in the current repo state, `_mock_mcp_enabled()` is set to **`False`** (live mode).
