# LinkedIn Outreach

Automation + workflow tooling for LinkedIn outreach: a LinkedIn MCP server, Claude skills, a queue worker.

## Install (one command)

From any directory, download and run the installer (uses [bash](https://www.gnu.org/software/bash/)):

```bash
curl -fsSL https://raw.githubusercontent.com/huangruoqi/LinkedIn-Outreach/main/install.sh | bash
```
- **First run:** run **`/setup-outreach`** in Claude Code to configure your operator profile from LinkedIn.
- **Outreach:** `connect to <linkedin-url>` in Claude CLI.
---

By default this clones or updates the repo at **`~/LinkedIn-Outreach`**. Override the directory with **`LINKEDIN_OUTREACH_DIR`**, the remote URL with **`LINKEDIN_OUTREACH_REPO`** (for forks), or **`git clone`** the repo and run **`./install.sh`** from the repository root so an existing clone is used instead.

### What the installer does

The script does **not** require **Make** (suitable for a fresh Mac before Xcode Command Line Tools). It:

- Installs **[uv](https://docs.astral.sh/uv/)** if it is missing, then runs **`uv sync`** and **`playwright install chromium`** (same as **`make install`**).
- **Default:** registers the LinkedIn MCP with Claude Code **`--scope user`** (all projects; stored in **`~/.claude.json`**). Copies each skill under **`outreach/skills/<name>/`** (with **`SKILL.md`**) into **`~/.claude/skills/<name>/`**. Set **`LINKEDIN_OUTREACH_SYNC_SKILLS_HOME=0`** to skip the skill copy only.
- **`--local`** (or **`LINKEDIN_OUTREACH_INSTALL_LOCAL=1`**): MCP **`--scope local`** only (this absolute project path); **does not** copy skills to **`~/.claude/skills`**. Same idea as **`make claude-install LOCAL=1`**.
- Pre-allows LinkedIn-Outreach in Claude Code settings: MCP (`mcp__linkedin`), all repo skills (`Skill(...)`), and maintenance bash (`bin/outreach-*`, `install.sh`, `uninstall.sh`, `make upgrade` / `uninstall` / `claude-install`). Writes to **`~/.claude/settings.json`** in default mode, or **`<repo>/.claude/settings.local.json`** with **`--local`**.
- If **`claude`** is missing, it prints next steps. **`./install.sh --help`** lists options.
- Launches **Google Chrome** on macOS at the default path with remote debugging (CDP) on port **9222** (same idea as **`make browser`**), opens **LinkedIn login**, and **pauses until you press Enter** after signing in. Playwright automation attaches to that live Chrome session. Skip the pause with **`./install.sh --skip-linkedin-login`**.
- Starts the **outreach web dashboard** in the background at **http://127.0.0.1:3847/** (logs: `logs/server.log`). Skip with **`./install.sh --no-web`**.

Once it finishes, run **`/setup-outreach`** in Claude Code to scrape your LinkedIn profile, review the draft persona, and save `outreach/config/persona.json`. Then open the dashboard at **http://127.0.0.1:3847/** — that's the production scheduler too.

## Documentation

- **[Web dashboard](docs/web-dashboard.md)** — the local UI + scheduler that runs the workflow unattended
- **[Architecture & capabilities](docs/architecture.md)** — components, MCP tool inventory, high-level + detailed workflow diagrams
- **[Manual install & Claude Desktop MCP](docs/install.md)** — prerequisites, `make install`, `claude_desktop_config.json`
- **[Quickstart (live + mock)](docs/quickstart.md)** — `make run`, live mode checklist, example prompts
- **[Claude skills](docs/skills.md)** — `setup-outreach`, `conversation-planner`, `send-connection-request`, `reply-to-post`, `sync-planner-persona-from-linkedin`
- **[Conversation planner config](docs/conversation-planner.md)** — runtime persona + campaign config without restarting the MCP server
- **[Operations](docs/operations.md)** — environment variables, data layout, Make targets
- **[Design notes](docs/designs/)** — internal design docs for per-connection routines, schedule-meeting MCP, regression tests, team rollout
