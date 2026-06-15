# Contributing to LinkedIn Outreach

Thanks for wanting to improve LinkedIn Outreach. This guide covers the dev setup, testing, and how to submit changes.

## Quick start

<!-- REPO_URL: update when the repo moves -->
```bash
git clone https://github.com/huangruoqi/LinkedIn-Outreach.git
cd LinkedIn-Outreach
make install            # uv sync + playwright install chromium
cp .env.example .env    # add your ANTHROPIC_API_KEY
```

## Project structure

```
tools/server.py              # MCP server (LinkedIn tools exposed to Claude)
outreach/browser.py          # Playwright browser automation (CDP connection)
outreach/skills/             # Claude Code skills (Markdown prompts)
outreach/config/             # Operator config (persona, campaign, style)
cron/server.py               # Unattended scheduler (connection sync, DM planning)
bin/                         # CLI utilities (upgrade check, settings, uninstall)
.github/workflows/           # CI (test matrix) and release (tag → GitHub Release)
testing/                     # Mock backend, regression harness, pytest suite
  tools/server.py            #   Mock-capable MCP server fork
  tools/mock.py              #   Scripted LinkedIn backend (no browser needed)
  outreach/mock/             #   Mock data tree + scenario fixtures
  tests/                     #   Pytest tests
docs/                        # Architecture, install, operations docs
```

## Day-to-day workflow

```bash
make browser        # launch Chrome with CDP on port 9222
make server         # start the queue-draining worker
make test           # run the pytest suite (delegates to testing/)
make status         # check if Chrome + worker are running
```

## Testing

All test commands run from the repo root.

| Command | What it tests |
|---------|---------------|
| `make test` | Full pytest suite (unit + mock integration) |
| `make test_conversation` | Conversation planner tests (needs `ANTHROPIC_API_KEY`) |
| `make regression` | End-to-end mock workflow via `claude -p` |

### Mock mode

Set `OUTREACH_MOCK=1` to route all MCP tools through the mock backend (`testing/tools/mock.py`) instead of a real LinkedIn session. The regression runner sets this automatically. Test fixtures live in `testing/outreach/mock/fixtures/`.

### Writing tests

- Tests go in `testing/tests/`.
- Use fictional personas for test data — never real LinkedIn profiles or emails.
- Rate limiter tests should monkeypatch `rate_limits_disabled()` rather than touching real state files.

## Skills

Skills are Markdown files in `outreach/skills/<name>/SKILL.md` that Claude Code discovers and invokes. To add or edit a skill:

1. Create or edit `outreach/skills/<name>/SKILL.md`.
2. Test by running `/<name>` in Claude Code (if skills are installed via `./install.sh`).
3. For local-only testing, symlink the skill dir into `~/.claude/skills/<name>/`.

## Environment variables

See [docs/operations.md](docs/operations.md) for the full list. Key ones:

- `ANTHROPIC_API_KEY` — required for conversation planner tests and API-mode planning
- `CDP_URL` — Chrome DevTools Protocol endpoint (default `http://localhost:9222`)
- `OUTREACH_MOCK` — set to `1` for mock mode (no real browser or LinkedIn session)
- `LINKEDIN_RATE_LIMIT_CONNECTIONS` / `_MESSAGES` / `_VIEWS` — override daily rate limits

## Submitting changes

1. Fork the repo and create a branch from `main`.
2. Make your changes. Keep diffs focused — one concern per PR.
3. Run `make test` and verify tests pass.
4. Open a pull request against `main` with a clear description of what changed and why.

## Code style

- Python 3.10+. No type stubs required but type hints are welcome.
- Keep error messages clear and actionable — the operator sees them in Claude Code.
- Rate-limiting and safety code is critical; changes there need tests.

## Releasing a new version

1. Update `VERSION` with the new version number.
2. Run `make sync-version` to update `pyproject.toml`.
3. Add an entry to `CHANGELOG.md` under the new version.
4. Commit the changes: `git add VERSION pyproject.toml CHANGELOG.md && git commit -m "release: v<version>"`.
5. Tag the commit: `git tag v<version>`.
6. Push both: `git push origin main v<version>`.
7. GitHub Actions creates the release automatically from the tag.

To verify the version files are in sync before committing: `make check-version`.

## Reporting issues

Open a GitHub issue. Include:

- What you did (steps to reproduce)
- What you expected
- What actually happened
- Your environment (OS, Python version, Chrome version)
