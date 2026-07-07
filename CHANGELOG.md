# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0.10] - 2026-07-07

### Changed
- Chrome now boots on demand: LinkedIn tool calls ping the CDP endpoint before attaching and launch it via `bin/browser-service start` if it's not up, waiting for CDP to come up. Session cookies persist on disk in the Chrome profile, so launchd/systemd no longer need to keep Chrome alive between calls.
- `cron.system_status` no longer logs a startup warning when Chrome's CDP endpoint is unreachable — that's now the expected steady state — and status output/JSON drop the stale "reinstall the always-on service" restart hint in favor of noting it starts on demand.

## [1.0.0.9] - 2026-07-05

### Fixed
- `send_message` no longer fails to message a connection with no existing thread (e.g. accepted without a note, so it never shows up in inbox/search) — falls back to the "Compose a new message" typeahead, matching the recipient by name and adding them
- Header/profile-URL verification now handles that new-conversation draft state (`.../messaging/thread/new/`) correctly: its title bar just reads "New message" (not the recipient's name), so verification now checks the conversation's profile card first — it carries the recipient's name and an already-resolved vanity-slug link, so no click-and-navigate is needed there either
- Added `testing/tools/send_message.py`, a manual live tool for sending a real DM via this flow

## [1.0.0.8] - 2026-07-05

### Fixed
- `send_message`'s thread-search fallback now prefers a result matching profile hints (name/header) over blindly taking the first visible search row, only falling back to "first visible" (with a warning) when nothing matches
- After opening a thread, the header name is checked against the expected recipient and the thread's profile link is clicked to confirm its resolved vanity URL matches the target profile — either mismatch now aborts the send instead of silently messaging the wrong person
- Added `testing/tools/check_thread_match.py` and expanded `test_send_message_thread_match.py` covering header and profile-URL matching

## [1.0.0.7] - 2026-07-05

### Fixed
- `LinkedInBrowser._attach` no longer fails to reconnect when the managed Chrome has zero open tabs — `connect_over_cdp` itself throws `Browser.setDownloadBehavior: Browser context management is not supported` in that state (rather than returning an empty `contexts` list), so the first connect attempt is now wrapped and falls back to opening a blank tab via the CDP HTTP endpoint before retrying
- `bin/browser-service` now prefers Playwright's bundled Chromium ("Chrome for Testing") over system Chrome/Chromium when resolving the browser binary, since it supports the CDP multi-context calls system Chrome rejects
- `install.sh` no longer overwrites an already-configured `outreach/config/persona.json` on reinstall — it now keeps the existing file by default (interactive: prompts before overwriting; non-interactive: always keeps it), matching the existing email-setup behavior
- `bin/outreach-upgrade` no longer forces `CHROME_BIN` to system Chrome before running `bin/browser-service install` — it now lets `resolve_chrome` pick Playwright's Chromium first, so upgrades don't silently regress back to the CDP bug above

### Upgrade note
- Existing installs: after upgrading, run `bin/browser-service install` to relaunch the managed browser under Playwright's Chromium. This reuses the same `--user-data-dir` profile, but the switch to a new browser binary drops the existing LinkedIn session — **you'll need to log in to LinkedIn again** in the relaunched window (or run `/setup-outreach` to restore it) before scraping/messaging tools will work.

## [1.0.0.6] - 2026-07-04

### Added
- `cron.system_status.check_services()` — probes cron + browser health, logging a warning for either that's unreachable
- `bin/outreach-update-check` now also probes cron/browser health and prints `SERVICE_DOWN <service> <url>` lines; `outreach-upgrade`, `setup-outreach`, and `send-connection-request` skills surface these to the operator at skill start (non-blocking, no email)

### Changed
- MCP server's background startup thread renamed `_run_upgrade_check` → `_run_system_check`; now runs the version check and the service health probes together, tracked in a single `_system_status` dict

## [1.0.0.5] - 2026-07-04

### Fixed
- `bin/outreach-upgrade` no longer crashes on macOS's stock bash (3.2) with `local_allow[@]: unbound variable` — replaced the empty-array pattern (unsafe under `set -u` before bash 4.4) with a plain string

## [1.0.0.4] - 2026-07-04

### Added
- `get_outreach_stats` MCP tool — reports outreach activity counts (connections sent/accepted, messages sent, replies) over a given time window
- `/stats` skill for querying outreach stats from Claude

## [1.0.0.3] - 2026-06-26

### Fixed
- Auth check now navigates to the LinkedIn feed before inspecting the URL, replacing the unreliable `li_at` cookie heuristic — correctly detects unauthenticated sessions when the tab is not already on LinkedIn
- Updated error messages in `browser.py` for clearer diagnostics on auth and connection failures
- LinkedIn profile action-row selector updated from legacy `artdeco-dropdown` to SDUI `aria-label='More'` — fixes connect/message button detection on the redesigned profile layout
- Connection sync sweep calls `is_connection_accepted` instead of `is_first_degree_connection` — aligns sweep logic with the correct acceptance-state check

## [1.0.0.2] - 2026-06-25

### Added
- `bin/cron-service` — systemd-compatible cron scheduler service with port-conflict guard and graceful shutdown
- `bin/browser-service` — standalone browser service with `json-status` subcommand for machine-readable health output
- `bin/outreach-upgrade` — in-place upgrade script that stops the cron service gracefully before reinstalling
- `cron/status_report.py` — structured status reporting for the cron scheduler
- `cron/system_status.py` — system-level health and status checks
- MCP `get_cron_status` tool for querying cron scheduler state from Claude
- Connection-request send verification: `_verify_connection_request_sent` polls after submission to confirm delivery
- Tests for connection-request verification (`test_connection_request_verify.py`), status report (`test_status_report.py`), and system status (`test_system_status.py`)

### Changed
- Removed worker queue (`outreach/worker.py`) — job dispatch is now handled directly by the cron scheduler
- `conversation_planner.json` replaced by `conversation_planner.json.example` to avoid committing live operator config
- `outreach/browser.py` substantially expanded with async probe helpers and connection-health utilities
- `install.sh` overhauled to register and start the new systemd service units
- `Makefile` simplified; removed duplicate `browser` target
- `tools/server.py` and `testing/tools/server.py` refactored to align with new service architecture

### Fixed
- Cron service stops gracefully before reinstall in `outreach-upgrade` (prevented stale lock files)
- Port-conflict guard restored in `start_cron_server` (was accidentally dropped in a prior refactor)
- `browser-service json-status` now uses `python3 -c json.dumps` for safe, locale-independent JSON output
- systemd `ExecStart` paths quoted to handle spaces in install directories
- `_verify_connection_request_sent` adds an initial delay before polling (prevents false negatives on slow pages)
- Replaced deprecated `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in async methods
- `probe_cron_server` now decouples `reachable` from `ok` so partial failures are reported accurately
- `_parse_iso` catches `AttributeError` for non-string values in JSONL log entries

## [1.0.0.1] - 2026-06-15

### Added
- Security policy (SECURITY.md) with vulnerability reporting instructions and scope

### Changed
- pyproject.toml now includes full package metadata: description, readme, license, keywords, classifiers, and project URLs

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
