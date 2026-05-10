#!/usr/bin/env bash
# LinkedIn Outreach — clone (if needed), Python env + Playwright Chromium,
# Claude Code MCP registration, and Chrome with CDP for LinkedIn sign-in.
# Does not require GNU Make (friendly to a fresh macOS install).
set -euo pipefail

REPO_URL="${LINKEDIN_OUTREACH_REPO:-https://github.com/huangruoqi/LinkedIn-Outreach.git}"
DEFAULT_DIR="${LINKEDIN_OUTREACH_DIR:-${HOME}/LinkedIn-Outreach}"

# Mirror Makefile defaults (override via environment)
CDP_PORT="${CDP_PORT:-9222}"
CHROME_PROFILE="${CHROME_PROFILE:-${HOME}/.linkedin-chrome-profile}"
CLAUDE_MCP_SERVER_NAME="${CLAUDE_MCP_SERVER_NAME:-linkedin}"
SKILL_SRC="${SKILL_SRC:-.claude/skills}"

info() { printf '%s\n' "[install] $*"; }
warn() { printf '%s\n' "[install] $*" >&2; }

repo_root_from_pyproject() {
  local dir="$1"
  [[ -f "${dir}/pyproject.toml" ]] || return 1
  grep -q 'name = "linkedin-outreach"' "${dir}/pyproject.toml" 2>/dev/null
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  info "uv not found; installing via https://astral.sh/uv/install.sh"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || {
    warn "uv was installed but is not on PATH. Open a new terminal, or run:"
    warn "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    exit 1
  }
}

ensure_repo() {
  REPO_ROOT=""
  if repo_root_from_pyproject "$(pwd)"; then
    REPO_ROOT="$(pwd)"
    info "Using current directory as repo: ${REPO_ROOT}"
    return 0
  fi

  local script_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if repo_root_from_pyproject "${script_dir}"; then
      REPO_ROOT="${script_dir}"
      info "Using script directory as repo: ${REPO_ROOT}"
      return 0
    fi
  fi

  command -v git >/dev/null 2>&1 || {
    warn "git is required. On macOS: install Xcode Command Line Tools (xcode-select --install) or Git from https://git-scm.com/downloads"
    exit 1
  }

  if [[ -d "${DEFAULT_DIR}/.git" ]] && repo_root_from_pyproject "${DEFAULT_DIR}"; then
    info "Updating existing clone at ${DEFAULT_DIR}"
    git -C "${DEFAULT_DIR}" pull --ff-only
    REPO_ROOT="${DEFAULT_DIR}"
    return 0
  fi

  info "Cloning ${REPO_URL} → ${DEFAULT_DIR}"
  git clone "${REPO_URL}" "${DEFAULT_DIR}"
  REPO_ROOT="${DEFAULT_DIR}"
}

# Equivalent to: make install  (uv sync + playwright install chromium)
install_project_deps() {
  cd "${REPO_ROOT}"
  info "Installing Python dependencies and Playwright Chromium…"
  uv sync
  uv run playwright install chromium
}

# Equivalent to: make claude-install  (stdio MCP; skills live in SKILL_SRC)
register_claude_mcp() {
  cd "${REPO_ROOT}"
  if ! command -v claude >/dev/null 2>&1; then
    printf '\n%s\n\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn "Claude Code CLI ('claude') is not installed or not on PATH."
    warn "Install Claude Code, then register the MCP server from this repo:"
    warn "  cd \"${REPO_ROOT}\""
    warn "  mkdir -p \"${SKILL_SRC}\""
    warn "  claude mcp remove --scope local ${CLAUDE_MCP_SERVER_NAME} 2>/dev/null || true"
    warn "  claude mcp add --transport stdio --scope local ${CLAUDE_MCP_SERVER_NAME} -- \\"
    warn "    uv run --project \"${REPO_ROOT}\" \"${REPO_ROOT}/tools/server.py\""
    warn "Docs: https://docs.anthropic.com/en/docs/claude-code"
    printf '%s\n\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return 0
  fi

  mkdir -p "${REPO_ROOT}/${SKILL_SRC}"
  claude mcp remove --scope local "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true
  claude mcp add --transport stdio --scope local "${CLAUDE_MCP_SERVER_NAME}" -- \
    uv run --project "${REPO_ROOT}" "${REPO_ROOT}/tools/server.py"
  info "Claude Code: MCP '${CLAUDE_MCP_SERVER_NAME}' registered (local scope). Skills: ${SKILL_SRC}/ — check: claude mcp list"
}

# Resolve Chrome: macOS default install path first (fresh Mac), then Linux common names.
chrome_binary() {
  local mac_chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  if [[ "$(uname -s)" == "Darwin" ]] && [[ -x "${mac_chrome}" ]]; then
    printf '%s' "${mac_chrome}"
    return 0
  fi
  if command -v google-chrome >/dev/null 2>&1; then
    command -v google-chrome
    return 0
  fi
  if command -v chromium >/dev/null 2>&1; then
    command -v chromium
    return 0
  fi
  if command -v chromium-browser >/dev/null 2>&1; then
    command -v chromium-browser
    return 0
  fi
  printf ''
}

# Equivalent to: make browser
launch_chrome_cdp() {
  local chrome
  chrome="$(chrome_binary)"
  if [[ -z "${chrome}" ]]; then
    warn "Google Chrome not found. On macOS install from https://www.google.com/chrome/"
    warn "Then start Chrome with CDP on port ${CDP_PORT} (same as README \"make browser\") or install Xcode CLI tools and use: make browser"
    return 0
  fi

  if command -v curl >/dev/null 2>&1 && curl -sf "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    info "Chrome already exposing CDP on port ${CDP_PORT} — skipping launch."
    info "Sign in to LinkedIn in that Chrome window if you have not yet."
    return 0
  fi

  info "Opening Chrome with remote debugging (CDP port ${CDP_PORT}). Sign in to LinkedIn in that window."
  info "Playwright attaches to this Chrome session (not a separate headless browser)."
  "${chrome}" \
    --remote-debugging-port="${CDP_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    --no-default-browser-check \
    --disable-extensions-except= \
    >/dev/null 2>&1 &
}

main() {
  ensure_uv
  ensure_repo
  [[ -n "${REPO_ROOT}" ]] || { warn "Could not determine repository root."; exit 1; }
  REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

  install_project_deps
  register_claude_mcp
  launch_chrome_cdp

  info "Setup finished."
  info "Repo: ${REPO_ROOT}"
  info "Optional: cp .env.example .env"
  info "Day-to-day you can use Make from the repo if you install Xcode CLI tools: make run, make browser, …"
}

main "$@"
