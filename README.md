# LinkedIn Outreach

Automation and workflow tooling for LinkedIn outreach: a Python project with a **LinkedIn MCP server** (`tools/server.py`) that Claude can call for browser actions and filesystem-backed pipeline state under `outreach/`.

## Prerequisites

- **Python** 3.10 or newer  
- **[uv](https://docs.astral.sh/uv/)** (recommended) for environments and `uv run`  
- **Google Chrome** (live mode): used with remote debugging so Playwright can attach  
- **Claude** desktop app with **Cowork** (or another MCP host that supports stdio MCP servers)
- **Make** (for `make install`, `make browser`, etc.)

### macOS: Install Make

Apple ships **GNU Make** with the Xcode Command Line Tools. If `make --version` fails in Terminal:

1. Run:

   ```bash
   xcode-select --install
   ```

2. Complete the installer dialog, then confirm:

   ```bash
   make --version
   ```

You can still use **`uv`** commands everywhere if you prefer not to install the Command Line Tools; `make` is only a convenience wrapper around those commands.

## Install the project

From the repository root:

```bash
make install
```

This runs `uv sync` and installs the Playwright Chromium browser. To do the same steps manually:

```bash
uv sync
uv run playwright install chromium
```

Confirm the server starts (stdio MCP; it will wait for input from a host):

```bash
uv run tools/server.py
```

Press Ctrl+C to exit. Use this when debugging; normally Claude starts the process for you.

## Claude Cowork

Cowork is the task-oriented workspace in the Claude desktop app. It can use **MCP tools** (including this repo’s LinkedIn server) the same way other Claude surfaces do, as long as the server is registered in your app config.

Optional **preferences** (example in [`claude_desktop_config.json`](claude_desktop_config.json)):

- `coworkScheduledTasksEnabled` — scheduled tasks in Cowork  
- `coworkWebSearchEnabled` — web search in Cowork  
- `sidebarMode` — e.g. `"task"` for task-focused sidebar  
- `ccdScheduledTasksEnabled` — scheduled tasks for Claude Code Desktop integration, if you use it  

Merge any keys you want into your **user** Claude config (see below). Do not commit secrets or machine-specific paths.

## MCP setup

### 1. Open the Claude app config

In the Claude desktop app, use **Menu → Developer → App Config File…** (wording may vary slightly by version). That opens `claude_desktop_config.json`.

On macOS the file usually lives at:

`~/Library/Application Support/Claude/claude_desktop_config.json`

Back up the file before editing.

### 2. Register the LinkedIn MCP server

Add an `mcpServers` entry that runs this repo’s server with `uv`. Replace the placeholders with **your** paths and your `uv` binary (`which uv`).

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/LinkedIn Outreach",
        "/absolute/path/to/LinkedIn Outreach/tools/server.py"
      ]
    }
  }
}
```

If you already have other MCP servers, merge the `"linkedin"` block into the existing `mcpServers` object instead of replacing the whole file.

The sample in [`claude_desktop_config.json`](claude_desktop_config.json) matches this shape; update every path to match your machine.

### 3. Restart Claude

Quit and reopen the Claude app so it reloads MCP configuration. In Cowork (or chat), you should see tools from the **linkedin** server (e.g. `scrape_profile`, `send_message`, `fetch_chat_history`, and the `outreach/*` filesystem helpers).

### 4. Live LinkedIn + Chrome (recommended for real sends)

The MCP server drives a logged-in Chrome session over the **Chrome DevTools Protocol** (default `http://localhost:9222`).

1. Start Chrome with debugging (from the repo root):

   ```bash
   make browser
   ```

2. Sign in to LinkedIn in that Chrome window.

3. Use Cowork / Claude with the MCP tools as usual.

If Chrome is not running with remote debugging, live tools will fail until `make browser` (or an equivalent launch) is used.

### Mock mode (optional, no browser)

For scripted tests without a browser, `tools/server.py` can run in mock mode when `_mock_mcp_enabled()` returns `True` (see the top of that file). In mock mode, tools use `tools/mock.py` instead of Playwright.

---

Reference Makefile targets: `make help` (browser, worker, tests, logs).
