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
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-3847}"
WEB_PID_FILE="${WEB_PID_FILE:-outreach/storage/web.pid}"
WEB_LOG="${WEB_LOG:-logs/server.log}"
CHROME_PROFILE="${CHROME_PROFILE:-${HOME}/.linkedin-chrome-profile}"
CLAUDE_MCP_SERVER_NAME="${CLAUDE_MCP_SERVER_NAME:-linkedin}"
SKILL_SRC="${SKILL_SRC:-outreach/skills}"
USER_CLAUDE_SKILLS="${USER_CLAUDE_SKILLS:-${HOME}/.claude/skills}"
# Set to 0 to skip copying skills into ~/.claude/skills (ignored when --local / INSTALL_LOCAL)
LINKEDIN_OUTREACH_SYNC_SKILLS_HOME="${LINKEDIN_OUTREACH_SYNC_SKILLS_HOME:-1}"
# 1 = MCP local scope + project skills only (same as ./install.sh --local)
INSTALL_LOCAL="${LINKEDIN_OUTREACH_INSTALL_LOCAL:-0}"
SKIP_LINKEDIN_LOGIN="${LINKEDIN_OUTREACH_SKIP_LINKEDIN_LOGIN:-0}"
LINKEDIN_LOGIN_URL="${LINKEDIN_LOGIN_URL:-https://www.linkedin.com}"
SKIP_EMAIL_SETUP="${LINKEDIN_OUTREACH_SKIP_EMAIL_SETUP:-0}"
GMAIL_APP_PASSWORD_URL="${GMAIL_APP_PASSWORD_URL:-https://myaccount.google.com/apppasswords}"
SKIP_PERSONA_SYNC="${LINKEDIN_OUTREACH_SKIP_PERSONA_SYNC:-0}"
SKIP_TONE_SETUP="${LINKEDIN_OUTREACH_SKIP_TONE_SETUP:-0}"
SKIP_WEB="${LINKEDIN_OUTREACH_SKIP_WEB:-0}"
PERSONA_PROFILE_URL="${PERSONA_PROFILE_URL:-https://www.linkedin.com/in/me/}"

REPO_ROOT=""
STEP_TOTAL=9
STEP_NUM=0
STEP_CURRENT=""
INSTALL_NOTES=()

info() { printf '%s\n' "[install] $*"; }
warn() { printf '%s\n' "[install] $*" >&2; }
note() { INSTALL_NOTES+=("$1"); }

step_begin() {
  STEP_NUM=$((STEP_NUM + 1))
  STEP_CURRENT="$1"
  info "[${STEP_NUM}/${STEP_TOTAL}] $1…"
}

step_done() {
  info "[${STEP_NUM}/${STEP_TOTAL}] $1 — done."
  STEP_CURRENT=""
}

on_err() {
  local ec=$?
  if [[ "${ec}" -ne 0 ]]; then
    warn "Install failed${STEP_CURRENT:+ at step \"${STEP_CURRENT}\"} (exit ${ec})."
    warn "Re-run ./install.sh from ${REPO_ROOT:-the repo} or see ./install.sh --help"
  fi
  exit "${ec}"
}
trap on_err ERR

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  Default (global):
    - Register LinkedIn MCP with Claude Code --scope user (available in all projects).
    - Copy repo skills (outreach/skills/<name>/) → ~/.claude/skills/<name>/ (unless disabled).

  --local
    - Register MCP with --scope local only (this absolute project path in ~/.claude.json).
    - Do not copy skills to ~/.claude/skills (repo outreach/skills only).

  Environment (same as --local when set to 1):
    LINKEDIN_OUTREACH_INSTALL_LOCAL=1

  --no-web
    Skip starting the outreach dashboard (same as LINKEDIN_OUTREACH_SKIP_WEB=1).
    Chrome, MCP registration, and dependency install still run.

  --skip-linkedin-login
    Do not pause for LinkedIn sign-in (same as LINKEDIN_OUTREACH_SKIP_LINKEDIN_LOGIN=1).

  --skip-email-setup
    Do not prompt for the Gmail app password / operator email
    (same as LINKEDIN_OUTREACH_SKIP_EMAIL_SETUP=1). Always skipped when stdin
    is not a TTY (e.g. curl | bash).

  --skip-persona-sync
    Do not run the sync-planner-persona-from-linkedin skill after sign-in
    (same as LINKEDIN_OUTREACH_SKIP_PERSONA_SYNC=1). Auto-skipped when the
    claude CLI is missing or Chrome CDP is unreachable.

  --skip-tone-setup
    Do not prompt for tone description / sample replies that seed
    message_rules.tone_guidelines and message_rules.style_examples
    (same as LINKEDIN_OUTREACH_SKIP_TONE_SETUP=1). Always skipped when stdin
    is not a TTY (e.g. curl | bash).

  Other:
    LINKEDIN_OUTREACH_SYNC_SKILLS_HOME=0   Skip global skill copy (default mode only).
    LINKEDIN_OUTREACH_SKIP_WEB=1           Skip dashboard (same as --no-web).
    WEB_HOST, WEB_PORT                     Dashboard bind (default 127.0.0.1:3847).
    SKILL_SRC   Override repo skill directory (default: outreach/skills).
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
      --skip-linkedin-login)
        SKIP_LINKEDIN_LOGIN=1
        shift
        ;;
      --skip-email-setup)
        SKIP_EMAIL_SETUP=1
        shift
        ;;
      --skip-persona-sync)
        SKIP_PERSONA_SYNC=1
        shift
        ;;
      --skip-tone-setup)
        SKIP_TONE_SETUP=1
        shift
        ;;
      --no-web)
        SKIP_WEB=1
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

require_cmd() {
  local cmd="$1" hint="$2"
  command -v "${cmd}" >/dev/null 2>&1 || {
    warn "Required command not found: ${cmd}"
    [[ -n "${hint}" ]] && warn "${hint}"
    exit 1
  }
}

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti ":${port}" >/dev/null 2>&1
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z localhost "${port}" >/dev/null 2>&1
    return $?
  fi
  return 1
}

describe_port_holder() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sed -n '2p' || true
  fi
}

check_cdp_port() {
  if curl -sf "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    return 0
  fi
  if port_in_use "${CDP_PORT}"; then
    local holder
    holder="$(describe_port_holder "${CDP_PORT}")"
    warn "Port ${CDP_PORT} is in use but is not Chrome CDP (/json/version failed)."
    [[ -n "${holder}" ]] && warn "  ${holder}"
    warn "Free the port, stop the other process, or retry with: CDP_PORT=9223 ./install.sh"
    note "warn: CDP port ${CDP_PORT} conflict — Chrome may not attach correctly"
  fi
}

preflight_checks() {
  step_begin "Checking prerequisites"
  if [[ "${BASH_VERSINFO[0]:-0}" -lt 3 ]]; then
    warn "Bash 3.2+ is required (you have ${BASH_VERSION:-unknown})."
    exit 1
  fi

  local os
  os="$(uname -s 2>/dev/null || printf 'unknown')"
  info "Platform: ${os}  |  Installer: ${BASH_SOURCE[0]:-install.sh}"
  if [[ ! -t 0 ]]; then
    info "Non-interactive stdin — email prompts and some confirmations are skipped automatically."
    note "info: non-interactive install (stdin is not a TTY)"
  fi
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Mode: --local (MCP local scope; skills stay in ${SKILL_SRC}/ only)"
  else
    info "Mode: global (MCP user scope; skills → ${USER_CLAUDE_SKILLS})"
  fi

  require_cmd curl "curl is needed to install uv and verify Chrome/dashboard health."
  step_done "Prerequisites"
}

ensure_uv() {
  step_begin "Ensuring uv (Python toolchain)"
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  if command -v uv >/dev/null 2>&1; then
    info "Found uv: $(command -v uv) ($(uv --version 2>/dev/null || echo 'version unknown'))"
    step_done "uv"
    return 0
  fi

  info "uv not found; installing via https://astral.sh/uv/install.sh"
  if ! curl -fsSL https://astral.sh/uv/install.sh | sh; then
    warn "uv install script failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
  fi
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || {
    warn "uv was installed but is not on PATH. Open a new terminal, or run:"
    warn "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    exit 1
  }
  info "Installed uv: $(uv --version 2>/dev/null || echo 'ok')"
  step_done "uv"
}

ensure_repo() {
  step_begin "Resolving repository"
  REPO_ROOT=""
  if repo_root_from_pyproject "$(pwd)"; then
    REPO_ROOT="$(pwd)"
    info "Using current directory: ${REPO_ROOT}"
    step_done "Repository"
    return 0
  fi

  local script_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if repo_root_from_pyproject "${script_dir}"; then
      REPO_ROOT="${script_dir}"
      info "Using script directory: ${REPO_ROOT}"
      step_done "Repository"
      return 0
    fi
  fi

  require_cmd git "On macOS: xcode-select --install  |  Or: https://git-scm.com/downloads"

  if [[ -d "${DEFAULT_DIR}" ]] && [[ ! -d "${DEFAULT_DIR}/.git" ]]; then
    if repo_root_from_pyproject "${DEFAULT_DIR}"; then
      REPO_ROOT="${DEFAULT_DIR}"
      info "Using existing checkout (no .git): ${REPO_ROOT}"
      step_done "Repository"
      return 0
    fi
    warn "${DEFAULT_DIR} exists but is not a LinkedIn-Outreach git checkout."
    warn "Remove it, set LINKEDIN_OUTREACH_DIR to another path, or clone manually:"
    warn "  git clone ${REPO_URL} \"${DEFAULT_DIR}\""
    exit 1
  fi

  if [[ -d "${DEFAULT_DIR}/.git" ]] && repo_root_from_pyproject "${DEFAULT_DIR}"; then
    info "Updating existing clone at ${DEFAULT_DIR}"
    if ! git -C "${DEFAULT_DIR}" pull --ff-only; then
      warn "git pull --ff-only failed (local commits or diverged branch?)."
      warn "Fix the repo under ${DEFAULT_DIR}, then re-run ./install.sh"
      exit 1
    fi
    REPO_ROOT="${DEFAULT_DIR}"
    step_done "Repository"
    return 0
  fi

  info "Cloning ${REPO_URL} → ${DEFAULT_DIR}"
  if ! git clone "${REPO_URL}" "${DEFAULT_DIR}"; then
    warn "git clone failed. Check network access and LINKEDIN_OUTREACH_REPO (${REPO_URL})."
    exit 1
  fi
  REPO_ROOT="${DEFAULT_DIR}"
  step_done "Repository"
}

install_project_deps() {
  step_begin "Installing Python dependencies and Playwright Chromium"
  cd "${REPO_ROOT}"
  info "Project requires Python >=3.10 (uv will fetch a compatible interpreter if needed)."
  if ! uv sync; then
    warn "uv sync failed. See output above; common fixes:"
    warn "  - Ensure network access for PyPI"
    warn "  - Delete .venv and re-run ./install.sh"
    exit 1
  fi
  local py_ver
  py_ver="$(uv run python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
  [[ -n "${py_ver}" ]] && info "Python environment: ${py_ver} ($(uv run which python 2>/dev/null || echo 'python'))"
  info "Installing Playwright Chromium (one-time download; may take a minute)…"
  if ! uv run playwright install chromium; then
    warn "playwright install chromium failed."
    warn "Retry: cd \"${REPO_ROOT}\" && uv run playwright install chromium"
    exit 1
  fi
  step_done "Python + Playwright"
}

sync_claude_skills_to_home() {
  step_begin "Syncing Claude skills"
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Skipped — --local keeps skills in ${REPO_ROOT}/${SKILL_SRC}/ only"
    note "skip: skills not copied to ${USER_CLAUDE_SKILLS} (--local)"
    step_done "Claude skills (repo only)"
    return 0
  fi
  [[ "${LINKEDIN_OUTREACH_SYNC_SKILLS_HOME}" == "1" ]] || {
    info "Skipped — LINKEDIN_OUTREACH_SYNC_SKILLS_HOME != 1"
    note "skip: skills not copied to ${USER_CLAUDE_SKILLS}"
    step_done "Claude skills"
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
    note "warn: no skills synced from ${src}"
  else
    info "Synced ${synced} skill(s) → ${USER_CLAUDE_SKILLS}/"
    note "ok: ${synced} skill(s) in ${USER_CLAUDE_SKILLS}/"
  fi
  step_done "Claude skills"
}

register_claude_mcp() {
  step_begin "Registering LinkedIn MCP with Claude Code"
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
    note "skip: Claude MCP not registered (claude CLI missing)"
    step_done "Claude MCP (skipped — install Claude Code)"
    return 0
  fi

  mkdir -p "${REPO_ROOT}/${SKILL_SRC}"
  claude mcp remove --scope user "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true
  claude mcp remove --scope local "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true
  claude mcp remove --scope project "${CLAUDE_MCP_SERVER_NAME}" 2>/dev/null || true

  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    if ! claude mcp add --transport stdio --scope local "${CLAUDE_MCP_SERVER_NAME}" -- \
      uv run --project "${REPO_ROOT}" "${REPO_ROOT}/tools/server.py"; then
      warn "claude mcp add failed (--scope local). Run: cd \"${REPO_ROOT}\" && make claude-install LOCAL=1"
      exit 1
    fi
    info "Registered MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope local). Verify: claude mcp list"
    note "ok: MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope local)"
  else
    if ! claude mcp add --transport stdio --scope user "${CLAUDE_MCP_SERVER_NAME}" -- \
      uv run --project "${REPO_ROOT}" "${REPO_ROOT}/tools/server.py"; then
      warn "claude mcp add failed (--scope user). Run: cd \"${REPO_ROOT}\" && make claude-install"
      exit 1
    fi
    info "Registered MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope user). Verify: claude mcp list"
    note "ok: MCP '${CLAUDE_MCP_SERVER_NAME}' (--scope user)"
  fi
  step_done "Claude MCP"
}

allow_linkedin_mcp_in_claude_settings() {
  # Pre-approve every LinkedIn MCP tool so Claude Code does not prompt on first use.
  # Rule "mcp__<server>" matches all tools from that MCP server.
  # Scope matches the MCP registration:
  #   default (--scope user) → ~/.claude/settings.json
  #   --local (--scope local) → <repo>/.claude/settings.local.json (gitignored)
  local rule="mcp__${CLAUDE_MCP_SERVER_NAME}"
  local target_file scope_label
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    mkdir -p "${REPO_ROOT}/.claude"
    target_file="${REPO_ROOT}/.claude/settings.local.json"
    scope_label="project-local"
  else
    mkdir -p "${HOME}/.claude"
    target_file="${HOME}/.claude/settings.json"
    scope_label="user"
  fi

  if ! uv run --project "${REPO_ROOT}" python - "${target_file}" "${rule}" <<'PY'
import json
import os
import sys

path, rule = sys.argv[1], sys.argv[2]

data: object = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
if not isinstance(data, dict):
    data = {}

perms = data.get("permissions")
if not isinstance(perms, dict):
    perms = {}
    data["permissions"] = perms

allow = perms.get("allow")
if not isinstance(allow, list):
    allow = []
    perms["allow"] = allow

if rule not in allow:
    allow.append(rule)

with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
  then
    warn "Could not update ${target_file} to allow ${rule}. Add it manually under permissions.allow."
    note "warn: could not pre-allow MCP tools in ${target_file}"
    return 0
  fi

  info "Claude permissions (${scope_label}): pre-allowed '${rule}' in ${target_file}"
  note "ok: MCP tools pre-allowed (${scope_label})"
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

wait_for_cdp() {
  local max_wait="${1:-40}"
  command -v curl >/dev/null 2>&1 || return 1
  local i
  for i in $(seq 1 "${max_wait}"); do
    if curl -sf "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

open_linkedin_tab_in_cdp() {
  command -v curl >/dev/null 2>&1 || return 0
  wait_for_cdp || return 0
  curl -sf -X PUT "http://localhost:${CDP_PORT}/json/new?${LINKEDIN_LOGIN_URL}" >/dev/null 2>&1 \
    || curl -sf "http://localhost:${CDP_PORT}/json/new?${LINKEDIN_LOGIN_URL}" >/dev/null 2>&1 \
    || true
}

launch_chrome_cdp() {
  step_begin "Launching Chrome with CDP for LinkedIn"
  local chrome
  chrome="$(chrome_binary)"
  if [[ -z "${chrome}" ]]; then
    warn "Google Chrome not found."
    warn "  macOS: https://www.google.com/chrome/"
    warn "  Linux: install google-chrome or chromium, then: make browser"
    note "skip: Chrome not installed — sign in manually before outreach"
    step_done "Chrome (skipped — install Chrome)"
    return 0
  fi
  info "Chrome binary: ${chrome}"
  info "Profile: ${CHROME_PROFILE}  |  CDP: http://localhost:${CDP_PORT}"

  if command -v curl >/dev/null 2>&1 && curl -sf "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    info "Chrome already exposing CDP on port ${CDP_PORT} — skipping launch."
    open_linkedin_tab_in_cdp
    note "ok: Chrome CDP already running on port ${CDP_PORT}"
    step_done "Chrome"
    return 0
  fi

  check_cdp_port

  info "Opening Chrome with remote debugging (CDP port ${CDP_PORT})."
  info "Playwright attaches to this live session (not headless Chromium)."
  "${chrome}" \
    --remote-debugging-port="${CDP_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    --no-default-browser-check \
    --disable-extensions-except= \
    "${LINKEDIN_LOGIN_URL}" \
    >/dev/null 2>&1 &

  info "Waiting for CDP (up to ~10s)…"
  if wait_for_cdp 40; then
    info "Chrome CDP is ready on port ${CDP_PORT}."
    note "ok: Chrome launched with CDP on port ${CDP_PORT}"
  else
    warn "Chrome started but CDP port ${CDP_PORT} is not ready yet."
    warn "Check for port conflicts: lsof -i :${CDP_PORT}   or retry: make browser"
    note "warn: Chrome CDP not ready on port ${CDP_PORT}"
  fi
  step_done "Chrome"
}

prompt_linkedin_login() {
  if [[ "${SKIP_LINKEDIN_LOGIN}" == "1" ]]; then
    info "Skipping LinkedIn sign-in prompt (--skip-linkedin-login)."
    note "skip: LinkedIn sign-in prompt (--skip-linkedin-login)"
    return 0
  fi

  if [[ -z "$(chrome_binary)" ]]; then
    warn "Chrome not found — sign in to LinkedIn manually before using outreach tools."
    return 0
  fi

  if ! wait_for_cdp; then
    warn "Chrome CDP is not reachable on port ${CDP_PORT}."
    warn "Run: make browser   then open ${LINKEDIN_LOGIN_URL} and sign in."
    note "warn: LinkedIn sign-in not confirmed (CDP unreachable)"
    return 0
  fi

  printf '\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Sign in to LinkedIn (required for outreach)"
  printf '%s\n' ""
  printf '%s\n' "  Use the Chrome window opened by this installer (profile:"
  printf '%s\n' "  ${CHROME_PROFILE})."
  printf '%s\n' ""
  printf '%s\n' "  1. Open or switch to: ${LINKEDIN_LOGIN_URL}"
  printf '%s\n' "  2. Sign in with your LinkedIn account."
  printf '%s\n' "  3. Confirm you see your feed or home — not the login page."
  printf '%s\n' ""
  printf '%s\n' "  The outreach engine (MCP, worker, dashboard skills) uses this"
  printf '%s\n' "  browser session only. Do not use a different Chrome profile."
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf '\n'

  if [[ -t 0 ]]; then
    read -r -p "[install] Press Enter when LinkedIn sign-in is complete: " _
    info "Continuing setup…"
    note "ok: LinkedIn sign-in confirmed"
  else
    warn "Non-interactive install — sign in to LinkedIn in Chrome before running outreach."
    note "info: sign in to LinkedIn in Chrome before outreach"
  fi
}

run_sync_planner_persona_skill() {
  local prompt="Run the sync-planner-persona-from-linkedin skill for profile ${PERSONA_PROFILE_URL}"
  local rerun_cmd="cd \"${REPO_ROOT}\" && claude -p '${prompt}'"

  if [[ "${SKIP_PERSONA_SYNC}" == "1" ]]; then
    info "Skipping planner persona sync (--skip-persona-sync)."
    note "skip: planner persona sync (--skip-persona-sync)"
    return 0
  fi
  if ! command -v claude >/dev/null 2>&1; then
    info "claude CLI not on PATH — skipping planner persona sync."
    info "After installing Claude Code, run: ${rerun_cmd}"
    note "skip: planner persona sync (claude CLI missing)"
    return 0
  fi
  if [[ "${SKIP_LINKEDIN_LOGIN}" == "1" ]] || [[ -z "$(chrome_binary)" ]]; then
    info "LinkedIn sign-in was skipped — skipping planner persona sync."
    info "After signing in, run: ${rerun_cmd}"
    note "skip: planner persona sync (LinkedIn sign-in skipped)"
    return 0
  fi
  if ! wait_for_cdp; then
    warn "Chrome CDP unreachable on port ${CDP_PORT} — skipping planner persona sync."
    warn "Start Chrome (make browser), sign in to LinkedIn, then run: ${rerun_cmd}"
    note "warn: planner persona sync skipped (CDP unreachable)"
    return 0
  fi

  printf '\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Sync planner persona from your LinkedIn profile (optional)"
  printf '%s\n' ""
  printf '%s\n' "  Runs the 'sync-planner-persona-from-linkedin' Skill via Claude CLI."
  printf '%s\n' "  Reads your signed-in LinkedIn profile (${PERSONA_PROFILE_URL}),"
  printf '%s\n' "  synthesizes persona + organization prose, then writes"
  printf '%s\n' "  outreach/config/persona.json so the conversation-planner"
  printf '%s\n' "  introduces you accurately."
  printf '%s\n' ""
  printf '%s\n' "  Takes ~30–60s and uses your Claude credits."
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf '\n'

  if [[ -t 0 ]]; then
    local reply=""
    read -r -p "[install] Sync planner persona from LinkedIn now? [Y/n] " reply || reply=""
    case "${reply}" in
      n|N|no|NO)
        info "Skipped — run later: ${rerun_cmd}"
        note "skip: planner persona sync (declined)"
        return 0
        ;;
    esac
  else
    info "Non-interactive install — running planner persona sync (override with --skip-persona-sync)."
  fi

  local model="${CLAUDE_MODEL:-haiku}"
  local perm="${REGRESSION_CLAUDE_PERMISSION_MODE:-bypassPermissions}"

  info "Invoking: claude -p \"${prompt}\" --model ${model} --permission-mode ${perm}"
  info "(streaming output; this may take 30–60 seconds)"
  printf '\n'

  if (cd "${REPO_ROOT}" && claude -p "${prompt}" --model "${model}" --permission-mode "${perm}"); then
    printf '\n'
    info "Planner persona sync complete. Inspect: outreach/config/persona.json"
    info "Or ask Claude in this repo: 'Show me my planner persona'."
    note "ok: planner persona synced to outreach/config/persona.json"
  else
    printf '\n'
    warn "claude -p exited non-zero. Re-run later with:"
    warn "  ${rerun_cmd}"
    note "warn: planner persona sync failed — re-run claude -p manually"
  fi
}

setup_planner_tone_and_examples() {
  step_begin "Configuring planner tone and style examples"

  local cfg_path="${REPO_ROOT}/outreach/config/conversation_planner.json"

  if [[ "${SKIP_TONE_SETUP}" == "1" ]]; then
    info "Skipping tone / style examples setup (--skip-tone-setup)."
    note "skip: planner tone / examples (--skip-tone-setup)"
    step_done "Planner tone / examples (skipped)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    info "Non-interactive install — skipping tone / style examples prompts."
    info "Run later via Claude Code: /setup-outreach (Step 3 — Tone & style examples)."
    note "skip: planner tone / examples (non-interactive stdin)"
    step_done "Planner tone / examples (skipped)"
    return 0
  fi
  if [[ ! -f "${cfg_path}" ]]; then
    info "Planner config not found at ${cfg_path} — skipping tone setup."
    info "It will be created with defaults the first time the MCP runs."
    note "skip: planner tone / examples (config missing)"
    step_done "Planner tone / examples (skipped)"
    return 0
  fi

  printf '\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Tone & style examples (optional but recommended)"
  printf '%s\n' ""
  printf '%s\n' "  The conversation-planner reads message_rules.tone,"
  printf '%s\n' "  message_rules.tone_guidelines, and message_rules.style_examples"
  printf '%s\n' "  to mirror how you actually write on LinkedIn."
  printf '%s\n' ""
  printf '%s\n' "  You can describe your tone (one line) and add 1–4 sample replies."
  printf '%s\n' "  Skip anything by pressing Enter — defaults stay in place."
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf '\n'

  local reply=""
  read -r -p "[install] Configure tone and sample replies now? [Y/n] " reply || reply=""
  case "${reply}" in
    n|N|no|NO)
      info "Skipped — run later via Claude Code: /setup-outreach (Step 3)."
      note "skip: planner tone / examples (declined)"
      step_done "Planner tone / examples (skipped)"
      return 0
      ;;
  esac

  local tone_short=""
  local tone_guidelines=""
  printf '\n'
  info "Tone (short adjective list, e.g. 'warm, casual, direct, no jargon')."
  info "Press Enter to keep the current tone in ${cfg_path}."
  read -r -p "[install] Tone: " tone_short || tone_short=""

  printf '\n'
  info "Tone guidelines (optional, longer prose). Single line."
  info "Examples: 'lowercase, occasional em-dashes, no emoji, ≤2 sentences'."
  info "Press Enter to skip."
  read -r -p "[install] Tone guidelines: " tone_guidelines || tone_guidelines=""

  local examples_payload=""
  printf '\n'
  info "Sample replies (recommended: 2–4). Press Enter on the reply prompt to stop."
  printf '\n'

  local idx=0
  while :; do
    idx=$((idx + 1))
    if [[ "${idx}" -gt 6 ]]; then
      info "Captured ${idx} example slots — that's plenty. Stopping."
      break
    fi

    local label="" context="" incoming="" example_reply=""
    info "Example ${idx}:"
    read -r -p "  Reply text (leave blank to finish): " example_reply || example_reply=""
    if [[ -z "${example_reply}" ]]; then
      idx=$((idx - 1))
      break
    fi
    read -r -p "  Label (optional, e.g. 'cold opener'): " label || label=""
    read -r -p "  Context (optional, e.g. 'they asked what we do'): " context || context=""
    read -r -p "  Incoming prospect message (optional; blank for outbound): " incoming || incoming=""

    if [[ -n "${examples_payload}" ]]; then
      examples_payload+=$'\x1f'
    fi
    examples_payload+="${label}"$'\x1e'"${context}"$'\x1e'"${incoming}"$'\x1e'"${example_reply}"
    printf '\n'
  done

  if [[ -z "${tone_short}" ]] && [[ -z "${tone_guidelines}" ]] && [[ -z "${examples_payload}" ]]; then
    info "No tone or examples provided — leaving config untouched."
    note "skip: planner tone / examples (no inputs)"
    step_done "Planner tone / examples (no changes)"
    return 0
  fi

  if ! TONE_CFG_PATH="${cfg_path}" \
       TONE_SHORT="${tone_short}" \
       TONE_GUIDELINES="${tone_guidelines}" \
       TONE_EXAMPLES="${examples_payload}" \
       uv run --project "${REPO_ROOT}" python - <<'PY'
import json
import os
import sys
import tempfile

path = os.environ["TONE_CFG_PATH"]
tone_short = os.environ.get("TONE_SHORT", "")
tone_guidelines = os.environ.get("TONE_GUIDELINES", "")
examples_raw = os.environ.get("TONE_EXAMPLES", "")

try:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, ValueError) as exc:
    print(f"[install] Could not read planner config: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(cfg, dict):
    print("[install] Planner config is not a JSON object; aborting tone update.", file=sys.stderr)
    sys.exit(1)

rules = cfg.setdefault("message_rules", {})
if not isinstance(rules, dict):
    print("[install] message_rules is not an object; aborting tone update.", file=sys.stderr)
    sys.exit(1)

if tone_short.strip():
    rules["tone"] = tone_short.strip()
if tone_guidelines.strip():
    rules["tone_guidelines"] = tone_guidelines.strip()
elif "tone_guidelines" not in rules:
    rules["tone_guidelines"] = ""

new_examples = []
if examples_raw:
    for chunk in examples_raw.split("\x1f"):
        if not chunk:
            continue
        parts = chunk.split("\x1e")
        while len(parts) < 4:
            parts.append("")
        label, context, incoming, reply = (p.strip() for p in parts[:4])
        if not reply:
            continue
        item = {"reply": reply}
        if label:
            item["label"] = label
        if context:
            item["context"] = context
        if incoming:
            item["incoming"] = incoming
        new_examples.append(item)

if new_examples:
    existing = rules.get("style_examples")
    if not isinstance(existing, list):
        existing = []
    rules["style_examples"] = existing + new_examples
elif "style_examples" not in rules:
    rules["style_examples"] = []

fd, tmp = tempfile.mkstemp(prefix=".tone-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
except Exception:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise

print(f"[install] Updated {path}")
print(f"[install]   tone:             {rules.get('tone', '')}")
print(f"[install]   tone_guidelines:  {rules.get('tone_guidelines', '') or '(blank)'}")
print(f"[install]   style_examples:   {len(rules.get('style_examples', []))} entry(ies)")
PY
  then
    warn "Could not update tone settings in ${cfg_path}."
    warn "Edit it manually or run: /setup-outreach in Claude Code."
    note "warn: planner tone / examples update failed"
    step_done "Planner tone / examples (failed)"
    return 0
  fi

  note "ok: planner tone / examples saved to outreach/config/conversation_planner.json"
  step_done "Planner tone / examples"
}

start_web_dashboard() {
  if [[ "${SKIP_WEB}" == "1" ]]; then
    step_begin "Starting outreach dashboard"
    info "Skipped — --no-web / LINKEDIN_OUTREACH_SKIP_WEB=1"
    note "skip: web dashboard not started (--no-web)"
    step_done "Web dashboard (skipped)"
    return 0
  fi

  step_begin "Starting outreach dashboard"
  cd "${REPO_ROOT}"
  local pid_file="${REPO_ROOT}/${WEB_PID_FILE}"
  local log_file="${REPO_ROOT}/${WEB_LOG}"
  local health_url="http://${WEB_HOST}:${WEB_PORT}/api/dashboard/health"
  local dashboard_url="http://${WEB_HOST}:${WEB_PORT}/"

  mkdir -p "$(dirname "${pid_file}")" "$(dirname "${log_file}")"

  if [[ -f "${pid_file}" ]]; then
    local old_pid
    old_pid="$(cat "${pid_file}")"
    if kill -0 "${old_pid}" 2>/dev/null && curl -sf "${health_url}" >/dev/null 2>&1; then
      info "Dashboard already running at ${dashboard_url} (pid=${old_pid})"
      note "ok: dashboard at ${dashboard_url}"
      step_done "Web dashboard"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  if command -v curl >/dev/null 2>&1 && curl -sf "${health_url}" >/dev/null 2>&1; then
    info "Dashboard already reachable at ${dashboard_url}"
    note "ok: dashboard already running at ${dashboard_url}"
    step_done "Web dashboard"
    return 0
  fi

  if port_in_use "${WEB_PORT}"; then
    local holder
    holder="$(describe_port_holder "${WEB_PORT}")"
    warn "Port ${WEB_PORT} is in use but dashboard health check failed."
    [[ -n "${holder}" ]] && warn "  ${holder}"
    warn "Free the port or set WEB_PORT, then run: make web"
    note "warn: web port ${WEB_PORT} conflict — dashboard not started"
    step_done "Web dashboard (port conflict)"
    return 0
  fi

  info "URL: ${dashboard_url}  |  Log: ${log_file}"
  if ! nohup uv run uvicorn web.server:app --host "${WEB_HOST}" --port "${WEB_PORT}" \
    >>"${log_file}" 2>&1 & then
    warn "Failed to start uvicorn. See ${log_file} or run: make web"
    note "warn: dashboard failed to start"
    step_done "Web dashboard (start failed)"
    return 0
  fi
  echo $! >"${pid_file}"

  if command -v curl >/dev/null 2>&1; then
    info "Waiting for dashboard health (up to ~10s)…"
    local i
    for i in $(seq 1 40); do
      if curl -sf "${health_url}" >/dev/null 2>&1; then
        info "Dashboard ready (pid=$(cat "${pid_file}"))"
        note "ok: dashboard at ${dashboard_url}"
        step_done "Web dashboard"
        return 0
      fi
      sleep 0.25
    done
    warn "Dashboard process started but health check did not succeed yet."
    warn "Tail logs: tail -f ${log_file}"
    warn "Restart: make stop-web && make web"
    note "warn: dashboard started but health check pending — see ${log_file}"
  else
    info "Dashboard process started (pid=$(cat "${pid_file}")); install curl to verify health."
    note "ok: dashboard process started (health not verified — no curl)"
  fi
  step_done "Web dashboard"
}

env_file_read_value() {
  local key="$1" envfile="$2"
  [[ -f "${envfile}" ]] || return 0
  grep -E "^[[:space:]]*${key}=" "${envfile}" 2>/dev/null \
    | head -n 1 \
    | sed -E "s/^[[:space:]]*${key}=//"
}

env_file_upsert() {
  local key="$1" value="$2" envfile="$3"
  local tmp
  tmp="$(mktemp "${envfile}.XXXXXX")"
  local replaced=0
  if [[ -f "${envfile}" ]]; then
    local line
    while IFS= read -r line || [[ -n "${line}" ]]; do
      if [[ "${line}" =~ ^[[:space:]]*#?[[:space:]]*${key}= ]]; then
        if [[ "${replaced}" -eq 0 ]]; then
          printf '%s=%s\n' "${key}" "${value}" >>"${tmp}"
          replaced=1
        fi
      else
        printf '%s\n' "${line}" >>"${tmp}"
      fi
    done <"${envfile}"
  fi
  if [[ "${replaced}" -eq 0 ]]; then
    printf '%s=%s\n' "${key}" "${value}" >>"${tmp}"
  fi
  mv "${tmp}" "${envfile}"
}

setup_email_notifications() {
  if [[ "${SKIP_EMAIL_SETUP}" == "1" ]]; then
    info "Skipping operator email setup (--skip-email-setup)."
    note "skip: email notifications (--skip-email-setup)"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    info "Non-interactive install — skipping Gmail SMTP prompts."
    info "Configure later by editing ${REPO_ROOT}/.env (see .env.example)."
    note "skip: email setup (non-interactive stdin)"
    return 0
  fi

  local envfile="${REPO_ROOT}/.env"
  if [[ ! -f "${envfile}" ]]; then
    if [[ -f "${REPO_ROOT}/.env.example" ]]; then
      cp "${REPO_ROOT}/.env.example" "${envfile}"
      info "Created ${envfile} from .env.example."
    else
      : >"${envfile}"
    fi
  fi
  chmod 600 "${envfile}" 2>/dev/null || true

  local existing_email existing_pass
  existing_email="$(env_file_read_value OPERATOR_EMAIL "${envfile}")"
  existing_pass="$(env_file_read_value SMTP_PASS "${envfile}")"

  printf '\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Operator email notifications (optional)"
  printf '%s\n' ""
  printf '%s\n' "  The LinkedIn-Outreach MCP can email you whenever:"
  printf '%s\n' "    • a prospect agrees to a meeting (schedule_meeting), or"
  printf '%s\n' "    • a sequence ends or is dropped (upsert_conversation)."
  printf '%s\n' ""
  printf '%s\n' "  Easiest setup: a Gmail address + a Google app password."
  printf '%s\n' "  You can skip this and configure later by editing .env."
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf '\n'

  local reply=""
  if [[ -n "${existing_email}" ]] && [[ -n "${existing_pass}" ]]; then
    info "Existing OPERATOR_EMAIL=${existing_email} and SMTP_PASS are already set in .env."
    read -r -p "[install] Reconfigure email notifications? [y/N] " reply || reply=""
    case "${reply}" in
      y|Y|yes|YES) ;;
      *)
        info "Keeping existing email configuration."
        note "ok: email notifications already configured in .env"
        return 0
        ;;
    esac
  else
    read -r -p "[install] Set up Gmail notifications now? [Y/n] " reply || reply=""
    case "${reply}" in
      n|N|no|NO)
        info "Skipped — edit ${envfile} later to enable notifications."
        note "skip: email notifications (declined)"
        return 0
        ;;
    esac
  fi

  printf '%s\n' "  1. Turn ON 2-Step Verification for your Google account (required):"
  printf '%s\n' "       https://myaccount.google.com/security"
  printf '%s\n' "  2. Generate an app password (label it 'LinkedIn-Outreach'):"
  printf '%s\n' "       ${GMAIL_APP_PASSWORD_URL}"
  printf '%s\n' "  3. Copy the 16-character password Google shows (spaces are fine)."
  printf '\n'

  if command -v open >/dev/null 2>&1; then
    open "${GMAIL_APP_PASSWORD_URL}" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${GMAIL_APP_PASSWORD_URL}" >/dev/null 2>&1 || true
  fi

  local email_re='^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
  local email="" password="" confirm="" default_prompt=""
  while [[ -z "${email}" ]]; do
    default_prompt=""
    [[ -n "${existing_email}" ]] && default_prompt=" [${existing_email}]"
    read -r -p "[install] Gmail address${default_prompt}: " email || email=""
    if [[ -z "${email}" ]] && [[ -n "${existing_email}" ]]; then
      email="${existing_email}"
    fi
    if [[ ! "${email}" =~ ${email_re} ]]; then
      warn "  '${email}' does not look like a valid email."
      email=""
    fi
  done

  while [[ -z "${password}" ]]; do
    read -r -s -p "[install] App password (input hidden): " password || password=""
    printf '\n'
    password="${password// /}"
    if [[ "${#password}" -lt 12 ]]; then
      warn "  Password looks too short — Gmail app passwords are 16 chars."
      password=""
      continue
    fi
    read -r -s -p "[install] Confirm app password: " confirm || confirm=""
    printf '\n'
    confirm="${confirm// /}"
    if [[ "${password}" != "${confirm}" ]]; then
      warn "  Passwords did not match — try again."
      password=""
    fi
  done

  env_file_upsert OPERATOR_EMAIL  "${email}"          "${envfile}"
  env_file_upsert SMTP_HOST       "smtp.gmail.com"    "${envfile}"
  env_file_upsert SMTP_PORT       "587"               "${envfile}"
  env_file_upsert SMTP_USER       "${email}"          "${envfile}"
  env_file_upsert SMTP_PASS       "${password}"       "${envfile}"
  env_file_upsert SMTP_FROM       "${email}"          "${envfile}"
  env_file_upsert SMTP_STARTTLS   "1"                 "${envfile}"
  env_file_upsert NOTIFY_DISABLED "0"                 "${envfile}"
  chmod 600 "${envfile}" 2>/dev/null || true

  info "Saved Gmail SMTP settings to ${envfile} (chmod 600)."
  note "ok: Gmail notifications configured in .env"
  info "Smoke-test the credentials:"
  info "  uv run --env-file .env python -c \"import sys; sys.path.insert(0,'tools'); import notify; print(notify.send_conversation_ended_email(prospect_id='smoke',prospect_name='Smoke Test',profile_url='',outreach_stage='ended',ended_reason='setup_test',ended_at='2026-05-23T18:00:00Z'))\""
  info "Expect 'sent' and an email in ${email} (check Spam on first send)."
}

print_final_summary() {
  local dashboard_url="http://${WEB_HOST}:${WEB_PORT}/"
  printf '\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Setup finished"
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  info "Repo: ${REPO_ROOT}"

  if ((${#INSTALL_NOTES[@]} > 0)); then
    printf '%s\n' ""
    info "Summary:"
    local n
    for n in "${INSTALL_NOTES[@]}"; do
      case "${n}" in
        ok:*)
          printf '  ✓ %s\n' "${n#ok: }"
          ;;
        skip:*)
          printf '  ○ %s\n' "${n#skip: }"
          ;;
        warn:*)
          printf '  ! %s\n' "${n#warn: }" >&2
          ;;
        info:*)
          printf '  · %s\n' "${n#info: }"
          ;;
        *)
          printf '  · %s\n' "${n}"
          ;;
      esac
    done
  fi

  printf '%s\n' ""
  info "Next steps:"
  if ! command -v claude >/dev/null 2>&1; then
    printf '  • Install Claude Code, then re-run: cd "%s" && ./install.sh\n' "${REPO_ROOT}"
  else
    printf '  • In Claude Code (this repo): /setup-outreach — persona, tone, and style examples\n'
    printf '  • Outreach: connect to <linkedin-url>\n'
  fi
  if [[ "${SKIP_WEB}" != "1" ]]; then
    printf '  • Dashboard: %s  (docs/web-dashboard.md)\n' "${dashboard_url}"
    printf '  • Stop dashboard: make stop-web   |   Status: make status\n'
  fi
  if [[ ! -f "${REPO_ROOT}/.env" ]]; then
    printf '  • Optional email alerts: cp .env.example .env && re-run ./install.sh\n'
  fi
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    printf '  • Open this exact folder as the workspace (local MCP is path-specific).\n'
  else
    printf '  • MCP is registered for all projects; skills live in %s/\n' "${USER_CLAUDE_SKILLS}"
  fi
  printf '  • Day-to-day: make browser   make web   make run\n'
  printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

main() {
  preflight_checks
  ensure_uv
  ensure_repo
  [[ -n "${REPO_ROOT}" ]] || { warn "Could not determine repository root."; exit 1; }
  REPO_ROOT="$(cd "${REPO_ROOT}" && pwd)"

  install_project_deps
  sync_claude_skills_to_home
  register_claude_mcp
  allow_linkedin_mcp_in_claude_settings
  launch_chrome_cdp
  prompt_linkedin_login
  run_sync_planner_persona_skill
  setup_planner_tone_and_examples
  setup_email_notifications
  start_web_dashboard

  print_final_summary
}

parse_args "$@"
main
