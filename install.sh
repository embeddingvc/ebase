#!/usr/bin/env bash
# LinkedIn Outreach — clone (if needed), Python env + Playwright Chromium,
# Claude Code MCP registration, and Chrome with CDP for LinkedIn sign-in.
# Does not require GNU Make (friendly to a fresh macOS install).
#
# Default: Claude MCP --scope user (all projects); sync skills → ~/.claude/skills
#   ./install.sh --local  → MCP --scope local (this project path only); no home skill sync
set -euo pipefail

REPO_URL="${LINKEDIN_OUTREACH_REPO:-https://github.com/huangruoqi/LinkedIn-Outreach.git}"
DEFAULT_DIR="${LINKEDIN_OUTREACH_DIR:-${HOME}/LinkedIn-Outreach}"

# Mirror Makefile defaults (override via environment)
CDP_PORT="${CDP_PORT:-9222}"
CHROME_PROFILE="${CHROME_PROFILE:-${HOME}/.linkedin-chrome-profile}"
CLAUDE_MCP_SERVER_NAME="${CLAUDE_MCP_SERVER_NAME:-linkedin}"
SKILL_SRC="${SKILL_SRC:-.claude/skills}"
USER_CLAUDE_SKILLS="${USER_CLAUDE_SKILLS:-${HOME}/.claude/skills}"
# Set to 0 to skip copying skills into ~/.claude/skills (ignored when --local / INSTALL_LOCAL)
LINKEDIN_OUTREACH_SYNC_SKILLS_HOME="${LINKEDIN_OUTREACH_SYNC_SKILLS_HOME:-1}"
# 1 = MCP local scope + project skills only (same as ./install.sh --local)
INSTALL_LOCAL="${LINKEDIN_OUTREACH_INSTALL_LOCAL:-0}"

info() { printf '%s\n' "[install] $*"; }
warn() { printf '%s\n' "[install] $*" >&2; }

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  Default (global):
    - Register LinkedIn MCP with Claude Code --scope user (available in all projects).
    - Copy repo skills (.claude/skills/<name>/) → ~/.claude/skills/<name>/ (unless disabled).

  --local
    - Register MCP with --scope local only (this absolute project path in ~/.claude.json).
    - Do not copy skills to ~/.claude/skills (repo .claude/skills only).

  Environment (same as --local when set to 1):
    LINKEDIN_OUTREACH_INSTALL_LOCAL=1

  Other:
    LINKEDIN_OUTREACH_SYNC_SKILLS_HOME=0   Skip global skill copy (default mode only).
    LINKEDIN_OUTREACH_DIR, LINKEDIN_OUTREACH_REPO, USER_CLAUDE_SKILLS, …

  curl | bash with flags:
    curl -fsSL …/install.sh | bash -s -- --local

  -h, --help   Show this message.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --local)
        INSTALL_LOCAL=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        warn "Unknown option: $1"
        usage >&2
        exit 1
        ;;
    esac
  done
}

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

install_project_deps() {
  cd "${REPO_ROOT}"
  info "Installing Python dependencies and Playwright Chromium…"
  uv sync
  uv run playwright install chromium
}

sync_claude_skills_to_home() {
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Skipping sync to ${USER_CLAUDE_SKILLS} (--local / INSTALL_LOCAL: project ${SKILL_SRC}/ only)"
    return 0
  fi
  [[ "${LINKEDIN_OUTREACH_SYNC_SKILLS_HOME}" == "1" ]] || {
    info "Skipping sync to ${USER_CLAUDE_SKILLS} (LINKEDIN_OUTREACH_SYNC_SKILLS_HOME != 1)"
    return 0
  }

  local src="${REPO_ROOT}/${SKILL_SRC}"
  if [[ ! -d "${src}" ]]; then
    warn "Skill source missing: ${src}"
    return 0
  fi

  mkdir -p "${USER_CLAUDE_SKILLS}"
  local synced=0
  local d n
  shopt -s nullglob
  for d in "${src}"/*/; do
    [[ -d "${d}" ]] || continue
    [[ -f "${d}/SKILL.md" ]] || continue
    n="$(basename "${d}")"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete "${d}" "${USER_CLAUDE_SKILLS}/${n}/"
    else
      rm -rf "${USER_CLAUDE_SKILLS}/${n}"
      mkdir -p "${USER_CLAUDE_SKILLS}/${n}"
      cp -a "${d}/." "${USER_CLAUDE_SKILLS}/${n}/"
    fi
    synced=$((synced + 1))
  done
  shopt -u nullglob

  if [[ "${synced}" -eq 0 ]]; then
    warn "No skill directories with SKILL.md under ${src}"
  else
    info "Synced ${synced} skill(s) → ${USER_CLAUDE_SKILLS}/"
  fi
}

register_claude_mcp() {
  cd "${REPO_ROOT}"
  if ! command -v claude >/dev/null 2>&1; then
    printf '\n%s\n\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn "Claude Code CLI ('claude') is not installed or not on PATH."
    warn "After installing Claude Code, from this repo run:"
    warn "  cd \"${REPO_ROOT}\" && ./install.sh              # user MCP + skills → ~/.claude/skills"
    warn "  cd \"${REPO_ROOT}\" && ./install.sh --local     # local MCP; skills stay in repo only"
    warn "  # or: make claude-install   /   make claude-install LOCAL=1"
    warn "Docs: https://docs.anthropic.com/en/docs/claude-code"
    printf '%s\n\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    return 0
  fi

  mkdir -p "${REPO_ROOT}/${SKILL_SRC}"
  claude mcp remove --scope user "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true
  claude mcp remove --scope local "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true
  claude mcp remove --scope project "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true

  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    claude mcp add --transport stdio --scope local "${CLAUDE_MCP_SERVER_NAME}" -- \
      uv run --project "${REPO_ROOT}" "${REPO_ROOT}/tools/server.py"
    info "Claude Code: MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope local, this project path only). Check: claude mcp list"
  else
    claude mcp add --transport stdio --scope user "${CLAUDE_MCP_SERVER_NAME}" -- \
      uv run --project "${REPO_ROOT}" "${REPO_ROOT}/tools/server.py"
    info "Claude Code: MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope user, all projects). Check: claude mcp list"
  fi
}

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

  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Mode: --local (MCP local scope; skills not copied to ${USER_CLAUDE_SKILLS})"
  else
    info "Mode: global (MCP user scope; skills → ${USER_CLAUDE_SKILLS})"
  fi

  install_project_deps
  sync_claude_skills_to_home
  register_claude_mcp
  launch_chrome_cdp

  info "Setup finished."
  info "Repo: ${REPO_ROOT}"
  info "Optional: cp .env.example .env"
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Open this exact folder as the workspace so local MCP matches ~/.claude.json."
  else
    info "LinkedIn MCP is registered for all projects; skills are under ${USER_CLAUDE_SKILLS}/."
  fi
  info "Day-to-day you can use Make if you install Xcode CLI tools: make run, make browser, …"
}

parse_args "$@"
main
