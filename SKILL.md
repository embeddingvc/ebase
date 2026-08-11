---
name: ebase
description: "Install ebase with agent"
---

## Install

Requires macOS, the `claude` CLI, and `uv`.

```bash
git clone https://github.com/embeddingvc/ebase.git ~/ebase && cd ~/ebase
./install.sh --skip-linkedin-login
```

`install.sh` checks prerequisites, installs dependencies, and registers the LinkedIn MCP server and skills. It's idempotent — safe to re-run. `--skip-linkedin-login` keeps it non-interactive (no blocking prompts, no live LinkedIn calls); sign in separately afterward via setup skill.

Once it finishes, open a **new** Claude Code session in this directory and run `/setup-outreach` there — a session already running (e.g. the one that ran the install command) won't see the newly registered MCP server or skill until it's restarted.
