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
