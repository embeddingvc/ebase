# ──────────────────────────────────────────────────────────────────────────────
# LinkedIn Outreach — testing/ (dashboard, mock backend, regression, pytest)
#
# Everything here is a development / QA tool. The production core (Claude
# skills, live MCP, cron scheduler) lives in the parent directory and has no
# dependency on this folder.
#
# `uv run` discovers the parent pyproject.toml, so all commands share the core
# virtualenv — no separate install step is needed.
# ──────────────────────────────────────────────────────────────────────────────

WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 3848

WEB_PID_FILE := ../outreach/storage/testing-web.pid
WEB_LOG      := ../logs/testing-web.log

.PHONY: help web web-bg stop-web test regression

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

web: ## Start the dashboard (dev/QA) in foreground (WEB_HOST / WEB_PORT)
	@echo "[testing-web] http://$(WEB_HOST):$(WEB_PORT)/  (mock view at /mock)"
	@uv run uvicorn web.server:app --host "$(WEB_HOST)" --port "$(WEB_PORT)"

web-bg: ## Start the dashboard in background (PID + log file)
	@mkdir -p ../outreach/storage ../logs
	@uv run uvicorn web.server:app --host "$(WEB_HOST)" --port "$(WEB_PORT)" \
	  >> $(WEB_LOG) 2>&1 & echo $$! > $(WEB_PID_FILE)
	@echo "[testing-web] started pid=$$(cat $(WEB_PID_FILE))  log=$(WEB_LOG)"

stop-web: ## Stop the background dashboard
	@if [ -f $(WEB_PID_FILE) ]; then \
	  kill "$$(cat $(WEB_PID_FILE))" 2>/dev/null || true; \
	  rm -f $(WEB_PID_FILE); \
	  echo "[testing-web] stopped"; \
	else \
	  echo "[testing-web] not running (no pid file)"; \
	fi

test: ## Run the full pytest suite
	@uv run pytest tests -v

regression: ## Mock workflow regression (needs `claude` CLI + auth)
	@OUTREACH_MOCK=1 uv run pytest tests/test_regression_workflow.py -v
