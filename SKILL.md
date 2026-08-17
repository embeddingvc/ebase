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

Once it finishes, run `/ebase-setup` — the wizard's persona/campaign/tone steps read and write
`outreach/config/` directly and work in this same session. Only the LinkedIn browser steps
(profile scrape, optional deep parse) need the newly-registered MCP server, which a session
already running (e.g. the one that ran the install command) won't see until it's restarted — the
wizard tells you if it hits that and which steps to finish after a restart.
