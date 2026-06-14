# Changelog

All notable changes to this project will be documented in this file.

## [0.0.6.0] - 2026-06-13

### Changed
- Rate limit defaults now match LinkedIn safe limits: 25 connections, 50 DMs, 100 profile views per day (previously 1/3/10)
- Rate limit env vars accept both naming conventions: `LINKEDIN_RATE_LIMIT_CONNECTION_REQUESTS` and the shorthand `LINKEDIN_RATE_LIMIT_CONNECTIONS` (same for DMs and profile views)
- Malformed primary env var now falls through to a valid alias instead of silently using the default

### Fixed
- `.gitignore` now covers full `outreach/prospects/`, `outreach/conversations/`, `outreach/logs/`, and `outreach/storage/` directories so teammates don't accidentally commit prospect data
- Removed tracked `.gitkeep` and evidence files from directories that should be user-local
