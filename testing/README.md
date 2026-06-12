# LinkedIn Outreach — testing/

Development and QA tooling for the LinkedIn-Outreach core. Nothing in this
folder is required for production use; the operator path is the core repo
(`./install.sh` → Claude skills + live MCP + cron scheduler).

## Contents

| Path | What it is |
|------|------------|
| `web/` | Full FastAPI dashboard (connections, routines, mock view at `/mock`) |
| `tools/server.py` | Mock-capable MCP server (fork of core `tools/server.py` with `OUTREACH_MOCK` support) |
| `tools/mock.py` | Scripted LinkedIn backend (no browser) |
| `outreach/mock/` | Mock data tree + scenario fixtures |
| `outreach/regression_harness.py` | Drives the full workflow loop via `claude -p` + mock MCP |
| `tests/` | Pytest suite (unit + regression) |
| `docs/web-dashboard.md` | Dashboard documentation |

## Running

All commands run from this directory. `uv run` picks up the parent
`pyproject.toml`, so the core virtualenv (FastAPI, Playwright, pytest, …) is
shared — no separate install.

```bash
make web         # dashboard at http://127.0.0.1:3848/ (mock view at /mock)
make test        # full pytest suite
make regression  # mock workflow regression (needs `claude` CLI + auth)
```

The dashboard does **not** run the routine scheduler — that lives in the core
cron server (`make -C .. cron`, port 3847). The dashboard is read-mostly plus
manual triggers (run-now, regression control).

## Mock mode

Set `OUTREACH_MOCK=1` to route MCP tools and the dashboard at the mock tree
(`testing/outreach/mock/`) instead of the live `outreach/` tree. The
regression runner sets this automatically for its subprocesses.

To run Claude against the mock backend (what `make regression` exercises via
`claude -p`), register the **testing** MCP server instead of the core one:

```bash
claude mcp add linkedin --scope user \
  -e OUTREACH_MOCK=1 \
  -- uv run python testing/tools/server.py
```

The production install (`make -C .. claude-install`) registers the core
live-only `tools/server.py`; re-run it to switch back.

## Data scopes

| Scope | Tree | Used by |
|-------|------|---------|
| live | `<repo>/outreach/` | operator data, core cron sweeps |
| mock | `testing/outreach/mock/` | regression runs, dashboard `/mock` view |

`OUTREACH_DATA_ROOT` overrides both (used by unit tests pointing at temp dirs).
