# ──────────────────────────────────────────────────────────────────────────────
# LinkedIn Outreach — Makefile
#
#  make run        Start Chrome + worker (the only command you need day-to-day)
#  make browser    Start Chrome with CDP debugging port (keeps existing profile)
#  make server     Start the queue-draining worker (requires Chrome running)
#  make stop       Kill the worker process
#  make test       Run the full exploration test suite
#  make smoke      Run smoke tests only (no credentials needed)
#  make install    Install Python dependencies + Playwright browsers
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

.PHONY: run browser server stop test smoke install logs queue status help

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

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run all exploration tests (set env vars to unlock tiers)
	uv run tests/test_playwright_exploration.py

smoke: ## Run smoke tests only (no credentials needed)
	uv run tests/test_playwright_exploration.py

browse: ## Run the human-behaviour session forever (Ctrl-C to stop)
	@echo "▶  Starting continuous browsing session. Ctrl-C to stop."
	FOREVER=1 LINKEDIN_POST_URL=$(LINKEDIN_POST_URL) \
	  uv run tests/test_playwright_exploration.py

# ── Install ───────────────────────────────────────────────────────────────────

install: ## Install Python deps + Playwright Chromium browser
	uv sync
	uv run playwright install chromium

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

status: ## Show whether Chrome + worker are currently running
	@echo "── Chrome (CDP port $(CDP_PORT)) ─────────────────"
	@curl -sf http://localhost:$(CDP_PORT)/json/version \
	  && echo "  ✅  Running" \
	  || echo "  ❌  Not running  (start with: make browser)"
	@echo "── Worker ───────────────────────────────────────"
	@if [ -f $(PID_FILE) ]; then \
	  PID=$$(cat $(PID_FILE)); \
	  kill -0 $$PID 2>/dev/null \
	    && echo "  ✅  Running  (pid=$$PID)" \
	    || echo "  ❌  PID file exists but process is gone  (stale: $(PID_FILE))"; \
	else \
	  echo "  ❌  Not running  (start with: make server)"; \
	fi

help: ## List all targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
