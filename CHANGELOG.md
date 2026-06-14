# Changelog

All notable changes to this project will be documented in this file.

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
