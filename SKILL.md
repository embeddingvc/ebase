---
name: ebase
description: "Install ebase with agent"
---

## Install

Requires macOS, the `claude` CLI, and `uv`.

```bash
git clone https://github.com/embeddingvc/ebase.git ~/ebase && cd ~/ebase
./install.sh
```

`install.sh` checks prerequisites, installs dependencies, and registers the LinkedIn MCP server and skills. It's idempotent — safe to re-run.
