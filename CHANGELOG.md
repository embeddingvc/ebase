# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-06-15

### Changed
- Repository moved to [embeddingvc/ebase](https://github.com/embeddingvc/ebase)
- Package renamed from `linkedin-outreach` to `ebase`
- Default install directory: `~/LinkedIn-Outreach` → `~/ebase`
- State directory: `~/.linkedin-outreach/` → `~/.ebase/` (automatic migration on first run)
- Toolkit env vars renamed: `LINKEDIN_OUTREACH_DIR` → `EBASE_DIR`, etc. (old names still work as fallbacks)
- Copyright updated to embeddingvc

### Unchanged
- MCP server name stays `linkedin`
- LinkedIn-specific env vars: `LINKEDIN_RATE_LIMIT_*`, `LINKEDIN_LOGIN_URL`
- All outreach skills, schemas, and browser automation internals

## [0.0.7.0] - 2026-06-14

### Added
- GitHub Actions CI pipeline: every push and PR to `main` runs the test suite automatically (Python 3.10 + 3.12 matrix), so broken commits get caught before merge
- GitHub Actions release workflow: push a `v*` tag to create a GitHub Release with changelog notes automatically
- `make sync-version` / `make check-version` targets to keep `VERSION` and `pyproject.toml` in sync
- `make check-repo-url` target to verify repo URLs are consistent across `install.sh`, `README.md`, and `CONTRIBUTING.md`
- Auto-upgrade check on MCP server startup: background thread notifies when a newer version is available
- `<!-- REPO_URL -->` marker comments in `README.md` and `CONTRIBUTING.md` so forkers can find-and-replace the repo URL in one pass
- Release process documented in `CONTRIBUTING.md` — contributors can now follow a step-by-step guide to cut a release

### Fixed
- `pyproject.toml` version now matches `VERSION` file (was `0.1.0`, corrected to track actual releases)
- `make sync-version` uses environment variable passing instead of shell interpolation (prevents code injection via VERSION content)
- `make check-repo-url` guards against empty repo slug extraction
- Backoff policy constants (`SYNC_DEFAULT`, `PLAN_DEFAULT`) restored to match design doc values
- Test isolation in `test_mock_fixtures.py` — monkeypatches `mock_base` to avoid leaking live session data

## [0.0.6.1] - 2026-06-14

### Added
- MIT license for open-source distribution
- CONTRIBUTING.md with dev setup, testing, and submission guidelines

### Changed
- `claude_desktop_config.json` removed from tracking; replaced with `.example` template with placeholder paths
- Scrubbed personal data from design docs and test fixtures (real LinkedIn URLs, realistic email addresses replaced with `example.com` domains)

### Fixed
- `docs/install.md` now references the `.example` config file instead of the removed original

## [0.0.6.0] - 2026-06-13

### Changed
- Rate limit defaults now match LinkedIn safe limits: 25 connections, 50 DMs, 100 profile views per day (previously 1/3/10)
- Rate limit env vars accept both naming conventions: `LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS` and the shorthand `LINKEDIN_RATE_LIMIT_CONNECTIONS` (same for DMs and profile views)
- Malformed primary env var now falls through to a valid alias instead of silently using the default

### Fixed
- `.gitignore` now covers full `outreach/prospects/`, `outreach/conversations/`, `outreach/logs/`, and `outreach/storage/` directories so teammates don't accidentally commit prospect data
- Removed tracked `.gitkeep` and evidence files from directories that should be user-local
