# Manual install & Claude Desktop MCP setup

The one-command installer in the main [README](../README.md) is the recommended path. Use this page if you want to install pieces by hand (e.g. on a CI box, in a fork, or behind a corporate proxy).

## Prerequisites

- **Python** 3.10 or newer
- **[uv](https://docs.astral.sh/uv/)** (recommended) for environments and `uv run`
- **Google Chrome** (live mode): used with remote debugging so Playwright can attach
- **Claude Desktop** (or another MCP host that supports stdio MCP servers)
- **Make** (for `make install`, `make browser`, etc.)

### macOS: install Make

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

Or use **`./install.sh`** from the repo root (skips cloning; uses **`uv`** and **`claude`** only — no **Make**). Use **`./install.sh --local`** for local MCP and repo-only skills.

This will:

- Create/sync the `uv` environment (`uv sync`)
- Install Playwright's Chromium runtime (`playwright install chromium`)

## Register the MCP server with Claude CLI

Recommended for most users:

- `make claude-install` — default: `--scope user` MCP + sync skills to `~/.claude/skills`
- `make claude-install LOCAL=1` — `--scope local` MCP only; skills stay under `outreach/skills/` in the repo

## Register the MCP server with Claude Desktop

1. `Settings` → `Developer` → `Edit Config`
2. Add (or merge) a `linkedin` server entry.

The sample in [`claude_desktop_config.json`](../claude_desktop_config.json) matches the expected shape; update paths for your machine:

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
