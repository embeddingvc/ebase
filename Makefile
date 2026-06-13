# ──────────────────────────────────────────────────────────────────────────────
# LinkedIn Outreach — Makefile
#
#  make run        Start Chrome + worker (the only command you need day-to-day)
#  make browser    Start Chrome with CDP debugging port (keeps existing profile)
#  make server     Start the queue-draining worker (requires Chrome running)
#  make stop       Kill the worker process
#  make test       Run the pytest suite (delegates to testing/)
#  make regression Run local conversation-planner regression (delegates to testing/)
#  make install    Install Python dependencies + Playwright browsers
#  make claude-install   Sync skills + register MCP (default: user scope + ~/.claude/skills; LOCAL=1: local MCP only)
#  make claude-cleanup   Remove linkedin MCP from user/local/project scopes; does not delete skill dirs
#  make cron         Scheduler + health API (http://127.0.0.1:3847/health)
#  make stop-cron    Stop cron server started by install.sh or background uvicorn
#  make logs       Tail the worker output log
#  make queue      Pretty-print the pending job queue
#  make status     Show whether Chrome + worker are running
# ──────────────────────────────────────────────────────────────────────────────

# ── Config (override via env or command-line) ─────────────────────────────────

CDP_PORT      ?= 9222
CDP_URL       ?= http://localhost:$(CDP_PORT)
CHROME_PROFILE?= $(HOME)/.linkedin-chrome-profile
POLL_INTERVAL ?= 5

# Resolve the Chrome binary across macOS and Linux.
CHROME_MAC    := /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
CHROME_LINUX  := $(shell which google-chrome 2>/dev/null || which chromium-browser 2>/dev/null || echo "")

ifeq ($(shell uname),Darwin)
  CHROME := $(CHROME_MAC)
else
  CHROME := $(CHROME_LINUX)
endif

# Paths
LOG_DIR  := outreach/logs
LOG_FILE := $(LOG_DIR)/worker.log
PID_FILE := outreach/storage/worker.pid
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 3847
CRON_PID_FILE := outreach/storage/cron.pid
CRON_LOG := logs/cron.log

# Claude Code CLI (https://docs.anthropic.com/en/docs/claude-code)
CLAUDE_MCP_SERVER_NAME := linkedin
# Canonical skill directories (tracked in git); override with make SKILL_SRC=path/to/skills
SKILL_SRC := outreach/skills
# Claude Code global skills dir (default claude-install syncs project skills here)
USER_CLAUDE_SKILLS := $(HOME)/.claude/skills
# Set LOCAL=1 or CLAUDE_INSTALL_LOCAL=1 for project-only MCP (--scope local) and no copy to $(USER_CLAUDE_SKILLS)
CLAUDE_INSTALL_LOCAL ?= 0
ifneq ($(LOCAL),)
override CLAUDE_INSTALL_LOCAL := $(LOCAL)
endif

.PHONY: run browser server stop stop-cron stop-web test test_conversation regression smoke install upgrade uninstall logs queue status help cron \
	claude-install claude-cleanup

# ── Default target ────────────────────────────────────────────────────────────

run: ## Start Chrome + worker (all-in-one)
	@echo "▶  Starting Chrome..."
	@$(MAKE) --no-print-directory browser
	@echo "▶  Waiting for Chrome to open CDP port $(CDP_PORT)..."
	@for i in $$(seq 1 20); do \
	  curl -sf http://localhost:$(CDP_PORT)/json/version > /dev/null && break; \
	  sleep 0.5; \
	done
	@echo "▶  Starting worker..."
	@$(MAKE) --no-print-directory server

# ── Browser ───────────────────────────────────────────────────────────────────

browser: ## Launch Chrome with remote debugging (stays open after make exits)
	@echo "[browser] Profile: $(CHROME_PROFILE)"
	@echo "[browser] CDP port: $(CDP_PORT)"
	@if curl -sf http://localhost:$(CDP_PORT)/json/version > /dev/null 2>&1; then \
	  echo "[browser] Chrome already running on port $(CDP_PORT) — skipping launch."; \
	else \
	  "$(CHROME)" \
	    --remote-debugging-port=$(CDP_PORT) \
	    --user-data-dir="$(CHROME_PROFILE)" \
	    --no-first-run \
	    --no-default-browser-check \
	    --disable-extensions-except= \
	    > /dev/null 2>&1 & \
	  echo "[browser] Launched (pid=$$!)"; \
	fi

# ── Worker / server ───────────────────────────────────────────────────────────

server: ## Start the queue-draining worker in the foreground
	@mkdir -p $(LOG_DIR) outreach/storage
	@echo "[worker] Logging to $(LOG_FILE)"
	CDP_URL=$(CDP_URL) POLL_INTERVAL=$(POLL_INTERVAL) \
	  uv run outreach/worker.py 2>&1 | tee -a $(LOG_FILE)

# ── Stop ──────────────────────────────────────────────────────────────────────

stop: ## Kill the running worker process
	@if [ -f $(PID_FILE) ]; then \
	  PID=$$(cat $(PID_FILE)); \
	  echo "[worker] Stopping pid=$$PID"; \
	  kill $$PID 2>/dev/null && echo "[worker] Stopped." || echo "[worker] Process not found."; \
	  rm -f $(PID_FILE); \
	else \
	  echo "[worker] No PID file found — worker may not be running."; \
	fi

stop-cron: ## Kill the cron scheduler server (uvicorn)
	@if [ -f $(CRON_PID_FILE) ]; then \
	  PID=$$(cat $(CRON_PID_FILE)); \
	  echo "[cron] Stopping pid=$$PID"; \
	  kill $$PID 2>/dev/null && echo "[cron] Stopped." || echo "[cron] Process not found."; \
	  rm -f $(CRON_PID_FILE); \
	else \
	  echo "[cron] No PID file — trying port $(WEB_PORT)…"; \
	  lsof -ti :$(WEB_PORT) | xargs kill 2>/dev/null && echo "[cron] Stopped." || echo "[cron] Not running."; \
	fi

stop-web: stop-cron ## Alias for stop-cron (dashboard moved to testing/)

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run the pytest suite (delegates to testing/)
	@$(MAKE) -C testing test

test_conversation: ## Run conversation-planner skill tests against Claude API (needs ANTHROPIC_API_KEY)
	@echo "▶  Running conversation-planner tests..."
	uv run testing/tests/test_conversation_planner.py

regression: ## Local pytest regression (Claude CLI + mock backend; delegates to testing/)
	@$(MAKE) -C testing regression

smoke: ## Run smoke tests only (no credentials needed)
	uv run testing/tests/test_playwright_exploration.py

browse: ## Run the human-behaviour session forever (Ctrl-C to stop)
	@echo "▶  Starting continuous browsing session. Ctrl-C to stop."
	FOREVER=1 LINKEDIN_POST_URL=$(LINKEDIN_POST_URL) \
	  uv run testing/tests/test_playwright_exploration.py

# ── Install ───────────────────────────────────────────────────────────────────

install: ## Install Python deps + Playwright Chromium browser
	uv sync
	uv run playwright install chromium

upgrade: ## Pull latest from origin/main, uv sync, refresh skills + MCP
	@bin/outreach-update-check --force 2>/dev/null || true
	@bin/outreach-upgrade

uninstall: ## Interactive uninstall (MCP, skills, optional data) — see ./uninstall.sh --help
	@./uninstall.sh

claude-uninstall: uninstall ## Alias for uninstall

claude-install: ## Default: sync $(SKILL_SRC) → $(USER_CLAUDE_SKILLS) + MCP --scope user | LOCAL=1: local MCP only, no home sync
	@command -v claude >/dev/null 2>&1 || { printf '%s\n' 'Claude Code CLI not found in PATH. Install: https://docs.anthropic.com/en/docs/claude-code' >&2; exit 1; }
	@command -v uv >/dev/null 2>&1 || { printf '%s\n' 'uv not found. Run: make install' >&2; exit 1; }
	@mkdir -p "$(CURDIR)/$(SKILL_SRC)"
	@if [ "$(CLAUDE_INSTALL_LOCAL)" = "1" ]; then \
	  printf '%s\n' "[claude-install] LOCAL=1: MCP --scope local; skills stay in $(SKILL_SRC)/ only"; \
	else \
	  mkdir -p "$(USER_CLAUDE_SKILLS)"; \
	  cd "$(CURDIR)" && for d in $(SKILL_SRC)/*/; do \
	    [ -d "$$d" ] || continue; \
	    [ -f "$$d/SKILL.md" ] || continue; \
	    n=$$(basename "$$d"); \
	    if command -v rsync >/dev/null 2>&1; then \
	      rsync -a --delete "$$d" "$(USER_CLAUDE_SKILLS)/$$n/"; \
	    else \
	      rm -rf "$(USER_CLAUDE_SKILLS)/$$n"; mkdir -p "$(USER_CLAUDE_SKILLS)/$$n"; \
	      cp -a "$${d%/}/." "$(USER_CLAUDE_SKILLS)/$$n/"; \
	    fi; \
	  done; \
	fi
	@claude mcp remove --scope user $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@claude mcp remove --scope local $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@cd "$(CURDIR)" && claude mcp remove --scope project $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@if [ "$(CLAUDE_INSTALL_LOCAL)" = "1" ]; then \
	  cd "$(CURDIR)" && claude mcp add --transport stdio --scope local $(CLAUDE_MCP_SERVER_NAME) -- \
	    uv run --project "$(CURDIR)" "$(CURDIR)/tools/server.py"; \
	  printf '%s\n' "Claude Code: MCP '$(CLAUDE_MCP_SERVER_NAME)' (--scope local). Check: claude mcp list"; \
	else \
	  cd "$(CURDIR)" && claude mcp add --transport stdio --scope user $(CLAUDE_MCP_SERVER_NAME) -- \
	    uv run --project "$(CURDIR)" "$(CURDIR)/tools/server.py"; \
	  printf '%s\n' "Claude Code: synced skills → $(USER_CLAUDE_SKILLS)/; MCP '$(CLAUDE_MCP_SERVER_NAME)' (--scope user). Check: claude mcp list"; \
	fi
	@if [ -x "$(CURDIR)/bin/outreach-allow-settings" ]; then \
	  if [ "$(CLAUDE_INSTALL_LOCAL)" = "1" ]; then \
	    OUTREACH_REPO_ROOT="$(CURDIR)" INSTALL_LOCAL=1 "$(CURDIR)/bin/outreach-allow-settings" add --local; \
	  else \
	    OUTREACH_REPO_ROOT="$(CURDIR)" INSTALL_LOCAL=0 "$(CURDIR)/bin/outreach-allow-settings" add; \
	  fi; \
	fi

claude-cleanup: ## Remove linkedin MCP from user/local/project scopes; does not delete $(SKILL_SRC) or $(USER_CLAUDE_SKILLS)
	@claude mcp remove --scope user $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@claude mcp remove --scope local $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@cd "$(CURDIR)" && claude mcp remove --scope project $(CLAUDE_MCP_SERVER_NAME) 2>/dev/null || true
	@cd "$(CURDIR)" && python3 -c "import json, pathlib; p=pathlib.Path('.mcp.json'); \
	  p.is_file() or exit(); d=json.loads(p.read_text()); \
	  (not (d.get('mcpServers') or {})) and p.unlink()" 2>/dev/null || true
	@printf '%s\n' "Claude Code: removed MCP '$(CLAUDE_MCP_SERVER_NAME)' (user/local/project); left $(SKILL_SRC)/ and $(USER_CLAUDE_SKILLS)/ untouched"

# ── Utilities ─────────────────────────────────────────────────────────────────

logs: ## Tail the worker log
	@mkdir -p $(LOG_DIR)
	@touch $(LOG_FILE)
	tail -f $(LOG_FILE)

queue: ## Pretty-print the pending job queue
	@echo "── Pending ──────────────────────────────"
	@cat outreach/queue/pending.json 2>/dev/null | python3 -m json.tool || echo "(empty)"
	@echo "── Completed ────────────────────────────"
	@cat outreach/queue/completed.json 2>/dev/null | python3 -m json.tool || echo "(empty)"
	@echo "── Failed ───────────────────────────────"
	@cat outreach/queue/failed.json 2>/dev/null | python3 -m json.tool || echo "(empty)"

status: ## Show whether Chrome, worker, and dashboard are running
	@echo "── Chrome (CDP port $(CDP_PORT)) ─────────────────"
	@curl -sf http://localhost:$(CDP_PORT)/json/version \
	  && echo "  ✅  Running" \
	  || echo "  ❌  Not running  (start with: make browser)"
	@echo "── Cron server (http://$(WEB_HOST):$(WEB_PORT)/health) ───"
	@curl -sf http://$(WEB_HOST):$(WEB_PORT)/health >/dev/null 2>&1 \
	  && echo "  ✅  Running" \
	  || echo "  ❌  Not running  (start with: make cron or ./install.sh)"
	@if [ -f $(CRON_PID_FILE) ]; then \
	  echo "      pid=$$(cat $(CRON_PID_FILE))  log=$(CRON_LOG)"; \
	fi
	@echo "── Worker ───────────────────────────────────────"
	@if [ -f $(PID_FILE) ]; then \
	  PID=$$(cat $(PID_FILE)); \
	  kill -0 $$PID 2>/dev/null \
	    && echo "  ✅  Running  (pid=$$PID)" \
	    || echo "  ❌  PID file exists but process is gone  (stale: $(PID_FILE))"; \
	else \
	  echo "  ❌  Not running  (start with: make server)"; \
	fi

cron: ## Start the scheduler + health API in foreground (WEB_HOST / WEB_PORT)
	@mkdir -p outreach/storage logs
	@echo "[cron] http://$(WEB_HOST):$(WEB_PORT)/health"
	@cd "$(CURDIR)" && uv run uvicorn cron.server:app --host "$(WEB_HOST)" --port "$(WEB_PORT)"

help: ## List all targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
