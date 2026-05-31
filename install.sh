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
PERSONA_PROFILE_URL="${PERSONA_PROFILE_URL:-https://www.linkedin.com/in/me/}"

info() { printf '%s\n' "[install] $*"; }
warn() { printf '%s\n' "[install] $*" >&2; }

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
    Skip starting the outreach dashboard (Chrome + MCP + deps still run).

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

  Other:
    LINKEDIN_OUTREACH_SYNC_SKILLS_HOME=0   Skip global skill copy (default mode only).
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
    return 0
  fi

  info "Claude permissions (${scope_label}): allowed all '${CLAUDE_MCP_SERVER_NAME}' MCP tools (${rule}) in ${target_file}"
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
  command -v curl >/dev/null 2>&1 || return 1
  local i
  for i in $(seq 1 40); do
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
  local chrome
  chrome="$(chrome_binary)"
  if [[ -z "${chrome}" ]]; then
    warn "Google Chrome not found. On macOS install from https://www.google.com/chrome/"
    warn "Then start Chrome with CDP on port ${CDP_PORT} (same as README \"make browser\") or install Xcode CLI tools and use: make browser"
    return 0
  fi

  if command -v curl >/dev/null 2>&1 && curl -sf "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    info "Chrome already exposing CDP on port ${CDP_PORT} — skipping launch."
    open_linkedin_tab_in_cdp
    return 0
  fi

  info "Opening Chrome with remote debugging (CDP port ${CDP_PORT})."
  info "Playwright attaches to this Chrome session (not a separate headless browser)."
  "${chrome}" \
    --remote-debugging-port="${CDP_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    --no-default-browser-check \
    --disable-extensions-except= \
    "${LINKEDIN_LOGIN_URL}" \
    >/dev/null 2>&1 &
  wait_for_cdp || warn "Chrome started but CDP port ${CDP_PORT} is not ready yet."
}

prompt_linkedin_login() {
  if [[ "${SKIP_LINKEDIN_LOGIN}" == "1" ]]; then
    info "Skipping LinkedIn sign-in prompt (--skip-linkedin-login)."
    return 0
  fi

  if [[ -z "$(chrome_binary)" ]]; then
    warn "Chrome not found — sign in to LinkedIn manually before using outreach tools."
    return 0
  fi

  if ! wait_for_cdp; then
    warn "Chrome CDP is not reachable on port ${CDP_PORT}."
    warn "Run: make browser   then open ${LINKEDIN_LOGIN_URL} and sign in."
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
  else
    warn "Non-interactive install — sign in to LinkedIn in Chrome before running outreach."
  fi
}

run_sync_planner_persona_skill() {
  local prompt="Run the sync-planner-persona-from-linkedin skill for profile ${PERSONA_PROFILE_URL}"
  local rerun_cmd="cd \"${REPO_ROOT}\" && claude -p '${prompt}'"

  if [[ "${SKIP_PERSONA_SYNC}" == "1" ]]; then
    info "Skipping planner persona sync (--skip-persona-sync)."
    return 0
  fi
  if ! command -v claude >/dev/null 2>&1; then
    info "claude CLI not on PATH — skipping planner persona sync."
    info "After installing Claude Code, run: ${rerun_cmd}"
    return 0
  fi
  if [[ "${SKIP_LINKEDIN_LOGIN}" == "1" ]] || [[ -z "$(chrome_binary)" ]]; then
    info "LinkedIn sign-in was skipped — skipping planner persona sync."
    info "After signing in, run: ${rerun_cmd}"
    return 0
  fi
  if ! wait_for_cdp; then
    warn "Chrome CDP unreachable on port ${CDP_PORT} — skipping planner persona sync."
    warn "Start Chrome (make browser), sign in to LinkedIn, then run: ${rerun_cmd}"
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
  else
    printf '\n'
    warn "claude -p exited non-zero. Re-run later with:"
    warn "  ${rerun_cmd}"
  fi
}

start_web_dashboard() {
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
      return 0
    fi
    rm -f "${pid_file}"
  fi

  if command -v curl >/dev/null 2>&1 && curl -sf "${health_url}" >/dev/null 2>&1; then
    info "Dashboard already reachable at ${dashboard_url} (not started by install.sh)"
    return 0
  fi

  info "Starting outreach dashboard at ${dashboard_url}"
  info "Log: ${log_file}"
  nohup uv run uvicorn web.server:app --host "${WEB_HOST}" --port "${WEB_PORT}" \
    >>"${log_file}" 2>&1 &
  echo $! >"${pid_file}"

  if command -v curl >/dev/null 2>&1; then
    local i
    for i in $(seq 1 40); do
      if curl -sf "${health_url}" >/dev/null 2>&1; then
        info "Dashboard ready (pid=$(cat "${pid_file}"))"
        return 0
      fi
      sleep 0.25
    done
    warn "Dashboard process started but health check did not succeed yet."
    warn "Check ${log_file} or run: make stop-web && make web"
  else
    info "Dashboard process started (pid=$(cat "${pid_file}")); install curl to verify health."
  fi
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
    return 0
  fi
  if [[ ! -t 0 ]]; then
    info "Non-interactive install — skipping Gmail SMTP prompts."
    info "Configure later by editing ${REPO_ROOT}/.env (see .env.example)."
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
        return 0
        ;;
    esac
  else
    read -r -p "[install] Set up Gmail notifications now? [Y/n] " reply || reply=""
    case "${reply}" in
      n|N|no|NO)
        info "Skipped — edit ${envfile} later to enable notifications."
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
  info "Smoke-test the credentials:"
  info "  uv run --env-file .env python -c \"import sys; sys.path.insert(0,'tools'); import notify; print(notify.send_conversation_ended_email(prospect_id='smoke',prospect_name='Smoke Test',profile_url='',outreach_stage='ended',ended_reason='setup_test',ended_at='2026-05-23T18:00:00Z'))\""
  info "Expect 'sent' and an email in ${email} (check Spam on first send)."
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
  allow_linkedin_mcp_in_claude_settings
  launch_chrome_cdp
  prompt_linkedin_login
  run_sync_planner_persona_skill
  setup_email_notifications
  start_web_dashboard

  info "Setup finished."
  info "Repo: ${REPO_ROOT}"
  if [[ ! -f "${REPO_ROOT}/.env" ]]; then
    info "Optional: cp .env.example .env   (then re-run ./install.sh for email setup)"
  fi
  info "Dashboard: http://${WEB_HOST}:${WEB_PORT}/  (docs: docs/web-dashboard.md)"
  info "Stop dashboard: make stop-web   Status: make status"
  if [[ "${INSTALL_LOCAL}" == "1" ]]; then
    info "Open this exact folder as the workspace so local MCP matches ~/.claude.json."
  else
    info "LinkedIn MCP is registered for all projects; skills are under ${USER_CLAUDE_SKILLS}/."
  fi
  info "Queue worker (optional): make run   Day-to-day: make browser, make web, …"
}

parse_args "$@"
main
