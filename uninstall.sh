#!/usr/bin/env bash
# LinkedIn Outreach — remove Claude/MCP integration and optional local data.
# Wrapper around bin/outreach-uninstall (mirrors install.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/bin/outreach-uninstall" "$@"
