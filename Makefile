# Makefile for HydraFlow — Intent in. Software out.

HYDRAFLOW_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PROJECT_ROOT := $(abspath $(HYDRAFLOW_DIR))
TARGET_REPO_ROOT ?= $(shell python3 -c 'from pathlib import Path; cur=Path.cwd().resolve(); roots=[p for p in [cur,*cur.parents] if (p/".git").exists()]; print((roots[-1] if roots else cur).as_posix())')

# Load .env if present (export all variables)
-include $(PROJECT_ROOT)/.env
export
VENV := $(PROJECT_ROOT)/.venv
UV := VIRTUAL_ENV=$(VENV) UV_CACHE_DIR=$(PROJECT_ROOT)/.uv-cache uv run --active

# Stamp file to track when deps were last synced
DEPS_STAMP := $(VENV)/.deps-synced

# Runtime overrides (used by `make hot`)
WORKERS ?= 3
MODEL ?= opus
REVIEW_MODEL ?= sonnet
BATCH_SIZE ?= 15
REVIEWERS ?= 5
HITL_WORKERS ?= 1
PLANNERS ?= 2
PLANNER_MODEL ?= opus
PORT ?= 5555
LOG_DIR ?= $(PROJECT_ROOT)/.hydraflow/logs

# Colors
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
RESET := \033[0m

# Docker agent image
DOCKER_IMAGE ?= ghcr.io/t-rav/hydraflow-agent:latest
DOCKER_BASE_IMAGE ?= ghcr.io/t-rav/hydraflow-agent-base:latest

.PHONY: help run dev dry-run clean clean-assets coverage cover smoke test test-fast test-cov lint lint-check lint-fix typecheck security quality quality-lite install setup status ui ui-dev ui-clean ensure-labels prep scaffold hot docker-build docker-ensure docker-test deps integration soak screenshot screenshot-update check-node-ui

check-node-ui:
	@cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh --version >/dev/null

help:
	@echo "$(BLUE)HydraFlow — Intent in. Software out.$(RESET)"
	@echo ""
	@echo "$(GREEN)Commands:$(RESET)"
	@echo "  make run            Start HydraFlow (backend + Vite frontend dev server)"
	@echo "  make dev            Alias for make run"
	@echo "  make dry-run        Dry run (log actions without executing)"
	@echo "  make clean          Remove all worktrees and state (API with offline fallback)"
	@echo "  make status         Show current HydraFlow state"
	@echo "  make test           Run unit tests"
	@echo "  make test-fast      Run unit tests (-x --tb=short)"
	@echo "  make coverage [MIN] Run coverage-focused test command (default 70)"
	@echo "  make cover [MIN]    Short alias for make coverage [MIN]"
	@echo "  make smoke          Run critical cross-system smoke tests"
	@echo "  make test-cov       Run tests with coverage report"
	@echo "  make lint           Auto-fix linting"
	@echo "  make lint-check     Check linting (no fix)"
	@echo "  make lint-fix       Auto-repair formatting/lint issues"
	@echo "  make typecheck      Run Pyright type checks"
	@echo "  make security       Run Bandit security scan"
	@echo "  make quality-lite   Lint + typecheck + security (parallel)"
	@echo "  make quality        quality-lite + test (parallel)"
	@echo "  make ensure-labels  Create HydraFlow labels in GitHub repo (API with offline fallback)"
	@echo "  make prep           Sync agent assets then run full prep (API with offline fallback)"
	@echo "  make scaffold       Generate baseline tests and CI configuration (API with offline fallback)"
	@echo "  make setup          Install hooks/assets for target repo ($(TARGET_REPO_ROOT))"
	@echo "  make install        Install dashboard dependencies"
	@echo "  make ui             Build React dashboard (src/ui/dist/)"
	@echo "  make ui-dev         Start React dashboard dev server"
	@echo "  make ui-clean       Remove src/ui/dist and node_modules"
	@echo "  make integration    Run multi-repo integration tests"
	@echo "  make soak           Run soak/load tests"
	@echo "  make hot            Send config update to running instance"
	@echo "  make deps           Sync dependencies via uv"
	@echo "  make docker-build   Build Hydra agent Docker image"
	@echo "  make docker-test    Build + smoke-test the agent image"
	@echo ""
	@echo "$(GREEN)Options (make run):$(RESET)"
	@echo "  PORT             Dashboard port (default: 5555)"
	@echo "  LOG_DIR          Log directory (default: .hydraflow/logs)"
	@echo "  WORKERS/MODEL/etc: set via .env or HYDRAFLOW_* env vars; use 'make hot' to update a live instance"
	@echo ""
	@echo "$(GREEN)Options (make hot — live config update):$(RESET)"
	@echo "  WORKERS          Max concurrent agents (default: 3)"
	@echo "  MODEL            Implementation model (default: opus)"
	@echo "  REVIEW_MODEL     Review model (default: sonnet)"
	@echo "  BATCH_SIZE       Issue batch size (default: 15)"
	@echo "  REVIEWERS        Max concurrent reviewers (default: 5)"
	@echo "  HITL_WORKERS     Max concurrent HITL workers (default: 1)"
	@echo "  PLANNERS         Max concurrent planners (default: 2)"
	@echo "  PLANNER_MODEL    Planner model (default: opus)"

docker-ensure:
	@docker image inspect $(DOCKER_IMAGE) >/dev/null 2>&1 \
		|| docker pull $(DOCKER_IMAGE) 2>/dev/null \
		|| $(MAKE) docker-build

EXECUTION_MODE ?= $(or $(HYDRAFLOW_EXECUTION_MODE),host)

ifeq ($(EXECUTION_MODE),docker)
run: check-node-ui docker-ensure hindsight
else
run: check-node-ui hindsight
endif
	@mkdir -p $(LOG_DIR)
	@echo "$(BLUE)Starting HydraFlow — backend :$(PORT) + frontend :5556$(RESET)"
	@echo "$(GREEN)Open http://localhost:5556 to use the dashboard$(RESET)"
	@trap 'kill 0' EXIT; \
	cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh install --silent 2>/dev/null && $(HYDRAFLOW_DIR)scripts/ui-npm.sh run dev 2>&1 | tee $(LOG_DIR)/vite.log & \
	cd $(HYDRAFLOW_DIR) && HYDRAFLOW_LOG_FILE=$(LOG_DIR)/server.log HYDRAFLOW_DASHBOARD_PORT=$(PORT) PYTHONPATH=src $(UV) python -m server & \
	wait

dev: run

dry-run:
	@echo "$(BLUE)HydraFlow dry run (server mode)$(RESET)"
	@cd $(HYDRAFLOW_DIR) && HYDRAFLOW_DRY_RUN=1 HYDRAFLOW_VERBOSE_LOGS=1 PYTHONPATH=src $(UV) python -m server
	@echo "$(GREEN)Dry run session exited$(RESET)"

clean:
	@echo "$(YELLOW)Cleaning up all HydraFlow worktrees and state...$(RESET)"
	@curl -sf -X POST "http://localhost:$(PORT)/api/admin/clean" 2>/dev/null \
		&& echo "$(GREEN)Cleanup finished (via API)$(RESET)" \
		|| (cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/run_admin_task.py clean && echo "$(GREEN)Cleanup finished$(RESET)")

clean-assets:
	@echo "$(BLUE)Removing HydraFlow assets from target repo...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/merge_assets.py \
		--target "$(TARGET_REPO_ROOT)" --clean

status:
	@echo "$(BLUE)HydraFlow State:$(RESET)"
	@if [ -f $(PROJECT_ROOT)/.hydraflow/state.json ]; then \
		cat $(PROJECT_ROOT)/.hydraflow/state.json | python -m json.tool; \
	else \
		echo "$(YELLOW)No state file found (HydraFlow has not run yet)$(RESET)"; \
	fi

$(DEPS_STAMP): pyproject.toml
	@echo "$(BLUE)Syncing dependencies...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && uv sync --all-extras
	@touch $(DEPS_STAMP)

deps: $(DEPS_STAMP)

TEST_COVERAGE := $(word 2,$(MAKECMDGOALS))
TEST_COVERAGE_IS_NUM := $(shell printf '%s' "$(TEST_COVERAGE)" | grep -Eq '^[0-9]+$$' && echo 1 || echo 0)
TEST_COVERAGE_DEFAULT ?= 70
TEST_COVERAGE_EFFECTIVE := $(if $(TEST_COVERAGE),$(TEST_COVERAGE),$(TEST_COVERAGE_DEFAULT))

ifneq ($(filter coverage cover,$(firstword $(MAKECMDGOALS))),)
ifneq ($(TEST_COVERAGE),)
ifneq ($(TEST_COVERAGE_IS_NUM),1)
$(error Usage: make coverage|cover [0-100])
endif
.PHONY: $(TEST_COVERAGE)
$(TEST_COVERAGE):
	@:
endif
endif

coverage: deps
	@echo "$(BLUE)Running HydraFlow unit tests...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ --cov=src --cov-fail-under=$(TEST_COVERAGE_EFFECTIVE) --cov-report=term-missing --cov-report=xml:coverage.xml -p no:xdist
	@echo "$(GREEN)All tests passed$(RESET)"

cover: coverage

test: deps
	@echo "$(BLUE)Running HydraFlow unit tests...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ -x -q
	@echo "$(GREEN)All tests passed$(RESET)"

smoke: deps
	@echo "$(BLUE)Running HydraFlow smoke tests...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest \
		tests/test_dashboard_init.py \
		tests/test_dashboard_lifecycle.py \
		tests/test_dashboard_routes_control.py \
		tests/test_dashboard_routes_core.py \
		tests/test_dashboard_routes_hitl.py \
		tests/test_dashboard_routes_issue_history.py \
		tests/test_dashboard_routes_metrics.py \
		tests/test_dashboard_routes_repo.py \
		tests/test_dashboard_routes_state.py \
		tests/test_runner_utils.py \
		tests/test_stream_parser.py -q
	@if [ -x "$(HYDRAFLOW_DIR)scripts/ui-npm.sh" ]; then \
		echo "$(BLUE)Running UI smoke tests...$(RESET)"; \
		cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh install --silent && $(HYDRAFLOW_DIR)scripts/ui-npm.sh test -- src/components/__tests__/App.test.jsx src/hooks/__tests__/useHydraFlowSocket.test.js; \
	else \
		echo "$(YELLOW)Skipping UI smoke tests (ui-npm helper script not found)$(RESET)"; \
	fi
	@echo "$(GREEN)Smoke tests passed$(RESET)"

integration: deps
	@echo "$(BLUE)Running multi-repo integration tests...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ -m integration -v
	@echo "$(GREEN)Integration tests passed$(RESET)"

soak: deps
	@echo "$(BLUE)Running soak/load tests (this may take a while)...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ -m soak -v --timeout=7200
	@echo "$(GREEN)Soak tests passed$(RESET)"

test-fast: deps
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ -x --tb=short

test-cov: deps
	@echo "$(BLUE)Running HydraFlow tests with coverage...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) pytest tests/ -v --cov=src --cov-fail-under=70 --cov-report=term-missing --cov-report=html:htmlcov -p no:xdist
	@echo "$(GREEN)All tests passed with coverage$(RESET)"

lint: deps
	@echo "$(BLUE)Linting HydraFlow (auto-fix)...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(UV) ruff check . --fix && $(UV) ruff format .
	@echo "$(GREEN)Linting complete$(RESET)"

lint-check: deps
	@echo "$(BLUE)Checking HydraFlow linting...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(UV) ruff check . && $(UV) ruff format . --check
	@echo "$(GREEN)Lint check passed$(RESET)"

lint-fix: lint
	@echo "$(GREEN)Auto-repair complete$(RESET)"

typecheck: deps
	@echo "$(BLUE)Running Pyright type checks...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(UV) pyright
	@echo "$(GREEN)Type check passed$(RESET)"

security: deps
	@echo "$(BLUE)Running Bandit security scan...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(UV) bandit -c pyproject.toml -r . --severity-level medium
	@echo "$(GREEN)Security scan passed$(RESET)"

layer-check:
	@echo "$(BLUE)Checking layer import direction...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(UV) python scripts/check_layer_imports.py
	@echo "$(GREEN)Layer check passed$(RESET)"

quality: deps
	@echo "$(BLUE)Running quality checks in parallel...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && ( \
		$(UV) ruff check . && $(UV) ruff format . --check && echo "[lint OK]" & \
		$(UV) pyright && echo "[typecheck OK]" & \
		$(UV) bandit -c pyproject.toml -r . --severity-level medium && echo "[security OK]" & \
		PYTHONPATH=src $(UV) pytest tests/ && echo "[tests OK]" & \
		$(UV) python scripts/check_layer_imports.py && echo "[layer-check OK]" & \
		wait_result=0; \
		for job in $$(jobs -p); do wait $$job || wait_result=1; done; \
		exit $$wait_result; \
	)
	@echo "$(GREEN)HydraFlow quality pipeline passed$(RESET)"

quality-lite: deps
	@echo "$(BLUE)Running lightweight quality checks...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && ( \
		$(VENV)/bin/ruff check . && \
		$(VENV)/bin/ruff format . --check && \
		echo "[lint OK]" && \
		$(VENV)/bin/pyright && \
		echo "[typecheck OK]" && \
		$(VENV)/bin/bandit -c pyproject.toml -r . --severity-level medium && \
		echo "[security OK]" \
	)
	@echo "$(GREEN)HydraFlow lightweight quality checks passed$(RESET)"

install:
	@echo "$(BLUE)Installing HydraFlow dashboard dependencies...$(RESET)"
	@VIRTUAL_ENV=$(VENV) uv pip install fastapi uvicorn websockets
	@echo "$(GREEN)Dashboard dependencies installed$(RESET)"

setup: deps
	@if ! command -v gh >/dev/null 2>&1; then \
		echo "$(BLUE)Installing gh CLI...$(RESET)"; \
		if command -v brew >/dev/null 2>&1; then \
			brew install gh; \
		elif command -v apt-get >/dev/null 2>&1; then \
			sudo apt-get update && sudo apt-get install -y gh; \
		elif command -v dnf >/dev/null 2>&1; then \
			sudo dnf install -y gh; \
		else \
			echo "$(RED)Error: Could not install gh CLI automatically. Install it manually: https://cli.github.com$(RESET)"; \
			exit 1; \
		fi; \
	fi
	@echo "  gh CLI: $$(gh --version | head -1)"
	@if ! gh auth status >/dev/null 2>&1; then \
		echo "$(YELLOW)gh CLI is not authenticated. Starting login...$(RESET)"; \
		gh auth login; \
	fi
	@echo "  gh user: $$(gh api user --jq .login)"
	@if [ ! -f "$(PROJECT_ROOT)/.env" ] && [ -f "$(PROJECT_ROOT)/.env.sample" ]; then \
		cp "$(PROJECT_ROOT)/.env.sample" "$(PROJECT_ROOT)/.env"; \
		echo "  .env created from .env.sample"; \
	elif [ -f "$(PROJECT_ROOT)/.env" ]; then \
		echo "  .env found: leaving existing file unchanged"; \
	else \
		echo "  .env.sample not found: skipping .env bootstrap"; \
	fi
	@if [ -f "$(PROJECT_ROOT)/AGENTS.md" ]; then \
		if [ ! -f "$(TARGET_REPO_ROOT)/AGENTS.md" ]; then \
			cp "$(PROJECT_ROOT)/AGENTS.md" "$(TARGET_REPO_ROOT)/AGENTS.md"; \
			echo "  AGENTS.md copied to target repo"; \
		else \
			echo "  AGENTS.md found in target repo; leaving existing file unchanged"; \
		fi; \
	else \
		echo "  AGENTS.md source not found: skipping copy"; \
	fi
	@echo "$(BLUE)Merging agent assets into target repo...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/merge_assets.py \
		--source "$(PROJECT_ROOT)" --target "$(TARGET_REPO_ROOT)"
	@git -C "$(TARGET_REPO_ROOT)" config core.hooksPath .githooks
	@if [ ! -f "$(TARGET_REPO_ROOT)/.gitignore" ]; then \
		touch "$(TARGET_REPO_ROOT)/.gitignore"; \
	fi
	@if ! grep -qx '\.hydraflow/prep' "$(TARGET_REPO_ROOT)/.gitignore"; then \
		printf '\n.hydraflow/prep\n' >> "$(TARGET_REPO_ROOT)/.gitignore"; \
		echo "  .gitignore updated: added .hydraflow/prep"; \
	fi
	@echo "$(BLUE)Ensuring HydraFlow lifecycle labels...$(RESET)"
	@echo "  target repo: $(TARGET_REPO_ROOT)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/run_admin_task.py ensure-labels || echo "$(YELLOW)  Label sync skipped (check gh auth and repo access)$(RESET)"
	@echo "$(BLUE)Detecting local agent assets (Claude/Codex/Pi)...$(RESET)"
	@if [ -d "$(PROJECT_ROOT)/.claude/hooks" ]; then \
		for HOOK in "$(PROJECT_ROOT)"/.claude/hooks/*.sh; do \
			[ -f "$$HOOK" ] || continue; \
			chmod +x "$$HOOK"; \
		done; \
		echo "  Claude hooks: executable bits refreshed"; \
	fi
	@if [ -d "$(PROJECT_ROOT)/.claude/commands" ]; then \
		echo "  Claude commands: detected in .claude/commands"; \
	fi
	@if [ -d "$(PROJECT_ROOT)/.codex/skills" ] || [ -f "$(PROJECT_ROOT)/AGENTS.md" ]; then \
		CODEX_HOME_DIR="$${CODEX_HOME:-$$HOME/.codex}"; \
		DEST="$$CODEX_HOME_DIR/skills"; \
		mkdir -p "$$DEST"; \
		INSTALLED=0; \
		PRUNED=0; \
		for SKILL_DIR in "$(PROJECT_ROOT)"/.codex/skills/*; do \
			[ -d "$$SKILL_DIR" ] || continue; \
			[ -f "$$SKILL_DIR/SKILL.md" ] || continue; \
			SKILL_NAME="$$(basename "$$SKILL_DIR")"; \
			rm -rf "$$DEST/$$SKILL_NAME"; \
			cp -R "$$SKILL_DIR" "$$DEST/$$SKILL_NAME"; \
			printf '%s\n' "$(PROJECT_ROOT)" > "$$DEST/$$SKILL_NAME/.hydraflow-managed"; \
			INSTALLED=$$((INSTALLED + 1)); \
			echo "  Codex skill installed: $$SKILL_NAME"; \
		done; \
		for INSTALLED_DIR in "$$DEST"/*; do \
			[ -d "$$INSTALLED_DIR" ] || continue; \
			MARKER="$$INSTALLED_DIR/.hydraflow-managed"; \
			[ -f "$$MARKER" ] || continue; \
			MARKED_SOURCE="$$(cat "$$MARKER" 2>/dev/null || true)"; \
			[ "$$MARKED_SOURCE" = "$(PROJECT_ROOT)" ] || continue; \
			SKILL_NAME="$$(basename "$$INSTALLED_DIR")"; \
			[ -f "$(PROJECT_ROOT)/.codex/skills/$$SKILL_NAME/SKILL.md" ] && continue; \
			rm -rf "$$INSTALLED_DIR"; \
			PRUNED=$$((PRUNED + 1)); \
			echo "  Codex stale skill pruned: $$SKILL_NAME"; \
		done; \
		if [ "$$INSTALLED" -eq 0 ]; then \
			echo "  Codex skills: no SKILL.md packages found under .codex/skills"; \
		else \
			echo "  Codex skills destination: $$DEST"; \
			echo "  Codex stale skills pruned: $$PRUNED"; \
			echo "  Restart Codex to load updated skills"; \
		fi; \
	fi
	@if command -v pi >/dev/null 2>&1; then \
		echo "  Pi CLI: $$(pi --version | head -1)"; \
		echo "  Pi config: ensure provider credentials are set (for example OPENAI_API_KEY or provider-specific key)"; \
		echo "  Pi usage: set HYDRAFLOW_*_TOOL=pi in .env to enable per-stage Pi backends"; \
		if [ -d "$(PROJECT_ROOT)/.pi" ]; then \
			PI_HOME_DIR="$${PI_CODING_AGENT_DIR:-$$HOME/.pi/agent}"; \
			INSTALLED=0; \
			for KIND in extensions skills prompt-templates themes; do \
				SRC_DIR="$(PROJECT_ROOT)/.pi/$$KIND"; \
				DEST_DIR="$$PI_HOME_DIR/$$KIND"; \
				[ -d "$$SRC_DIR" ] || continue; \
				mkdir -p "$$DEST_DIR"; \
				for ENTRY in "$$SRC_DIR"/*; do \
					[ -e "$$ENTRY" ] || continue; \
					NAME="$$(basename "$$ENTRY")"; \
					rm -rf "$$DEST_DIR/$$NAME"; \
					cp -R "$$ENTRY" "$$DEST_DIR/$$NAME"; \
					INSTALLED=$$((INSTALLED + 1)); \
					echo "  Pi $$KIND installed: $$NAME"; \
				done; \
			done; \
			if [ "$$INSTALLED" -eq 0 ]; then \
				echo "  Pi assets: .pi/ exists but no installable entries found under extensions/skills/prompt-templates/themes"; \
			else \
				echo "  Pi assets destination: $$PI_HOME_DIR"; \
			fi; \
		fi; \
	else \
		echo "  Pi CLI: not found (install from https://pi.dev/ if you want Pi backend support)"; \
	fi
	@echo "$(GREEN)Setup complete$(RESET)"
	@echo "  pre-commit: make lint-check (when staged Python files exist)"
	@echo "  pre-push:   make quality-lite"

REPO_SLUG := $(shell git remote get-url origin 2>/dev/null | sed 's|.*github\.com[:/]||;s|\.git$$||')

prep: deps
	@echo "$(BLUE)Ensuring target repo has latest agent assets first...$(RESET)"
	@$(MAKE) setup TARGET_REPO_ROOT="$(TARGET_REPO_ROOT)"
	@echo "$(BLUE)Scanning repo and scaffolding CI/tests...$(RESET)"
	@curl -sf -X POST "http://localhost:$(PORT)/api/admin/prep" 2>/dev/null \
		&& echo "$(GREEN)Prep complete (via API)$(RESET)" \
		|| (cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/run_admin_task.py prep && echo "$(GREEN)Prep complete$(RESET)")

scaffold: deps
	@echo "$(BLUE)Generating baseline tests and CI configuration...$(RESET)"
	@curl -sf -X POST "http://localhost:$(PORT)/api/admin/scaffold" 2>/dev/null \
		&& echo "$(GREEN)Scaffold complete (via API)$(RESET)" \
		|| (cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/run_admin_task.py scaffold && echo "$(GREEN)Scaffold complete$(RESET)")

scaffold-loop:
	@python scripts/scaffold_loop.py $(NAME) $(LABEL) $(DESC) --interval $(or $(INTERVAL),3600)

ensure-labels: deps
	@echo "$(BLUE)Creating HydraFlow lifecycle labels...$(RESET)"
	@curl -sf -X POST "http://localhost:$(PORT)/api/admin/ensure-labels" 2>/dev/null \
		&& echo "$(GREEN)Label sync complete (via API)$(RESET)" \
		|| (cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/run_admin_task.py ensure-labels && echo "$(GREEN)Label sync complete$(RESET)")

hot:
	@echo "$(BLUE)Sending config update to running HydraFlow instance on :$(PORT)...$(RESET)"
	@JSON='{"persist": true'; \
	[ "$(origin WORKERS)" = "command line" ] && JSON="$$JSON, \"max_workers\": $(WORKERS)"; \
	[ "$(origin MODEL)" = "command line" ] && JSON="$$JSON, \"model\": \"$(MODEL)\""; \
	[ "$(origin BATCH_SIZE)" = "command line" ] && JSON="$$JSON, \"batch_size\": $(BATCH_SIZE)"; \
	[ "$(origin REVIEWERS)" = "command line" ] && JSON="$$JSON, \"max_reviewers\": $(REVIEWERS)"; \
	[ "$(origin REVIEW_MODEL)" = "command line" ] && JSON="$$JSON, \"review_model\": \"$(REVIEW_MODEL)\""; \
	[ "$(origin PLANNERS)" = "command line" ] && JSON="$$JSON, \"max_planners\": $(PLANNERS)"; \
	[ "$(origin PLANNER_MODEL)" = "command line" ] && JSON="$$JSON, \"planner_model\": \"$(PLANNER_MODEL)\""; \
	[ "$(origin HITL_WORKERS)" = "command line" ] && JSON="$$JSON, \"max_hitl_workers\": $(HITL_WORKERS)"; \
	JSON="$$JSON}"; \
	curl -s -X PATCH "http://localhost:$(PORT)/api/control/config" \
		-H "Content-Type: application/json" \
		-d "$$JSON" | python -m json.tool
	@echo "$(GREEN)Config update sent$(RESET)"

ui: check-node-ui
	@echo "$(BLUE)Building HydraFlow React dashboard...$(RESET)"
	@cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh install && $(HYDRAFLOW_DIR)scripts/ui-npm.sh run build
	@echo "$(GREEN)Dashboard built → src/ui/dist/$(RESET)"

ui-dev: check-node-ui
	@echo "$(BLUE)Starting HydraFlow dashboard dev server...$(RESET)"
	@cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh install && $(HYDRAFLOW_DIR)scripts/ui-npm.sh run dev

ui-clean:
	@echo "$(YELLOW)Cleaning dashboard build artifacts...$(RESET)"
	@rm -rf $(HYDRAFLOW_DIR)src/ui/dist $(HYDRAFLOW_DIR)src/ui/node_modules
	@echo "$(GREEN)Dashboard cleaned$(RESET)"

screenshot: check-node-ui
	@echo "$(BLUE)Capturing deterministic screenshots...$(RESET)"
	@cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh ci && $(HYDRAFLOW_DIR)scripts/ui-npm.sh exec playwright install --with-deps chromium && $(HYDRAFLOW_DIR)scripts/ui-npm.sh run screenshot
	@echo "$(GREEN)Screenshots captured → src/ui/e2e/screenshots/$(RESET)"

screenshot-update: check-node-ui
	@echo "$(BLUE)Updating screenshot baselines...$(RESET)"
	@cd $(HYDRAFLOW_DIR)src/ui && $(HYDRAFLOW_DIR)scripts/ui-npm.sh ci && $(HYDRAFLOW_DIR)scripts/ui-npm.sh exec playwright install --with-deps chromium && $(HYDRAFLOW_DIR)scripts/ui-npm.sh run screenshot:update
	@echo "$(GREEN)Screenshot baselines updated → src/ui/e2e/screenshots/$(RESET)"

hindsight:
	@echo "$(BLUE)Starting Hindsight semantic memory server...$(RESET)"
	docker compose up -d hindsight
	@echo "$(GREEN)Hindsight running — API: http://localhost:8888  UI: http://localhost:9999$(RESET)"

hindsight-stop:
	@echo "$(BLUE)Stopping Hindsight...$(RESET)"
	docker compose down hindsight
	@echo "$(GREEN)Hindsight stopped$(RESET)"

docker-build:
	@echo "$(BLUE)Building Hydra agent Docker image...$(RESET)"
	@docker pull $(DOCKER_BASE_IMAGE) 2>/dev/null \
		&& echo "$(GREEN)Using pre-built base image$(RESET)" \
		&& docker build --platform linux/amd64 --build-arg BASE_IMAGE=$(DOCKER_BASE_IMAGE) -f Dockerfile.agent -t $(DOCKER_IMAGE) . \
		|| ( echo "$(YELLOW)Base image not available — full build$(RESET)" \
		&& docker build --platform linux/amd64 -f Dockerfile.agent -t $(DOCKER_IMAGE) . )
	@echo "$(GREEN)Image built: $(DOCKER_IMAGE)$(RESET)"

docker-test: docker-build
	@echo "$(BLUE)Running agent image smoke test...$(RESET)"
	docker run --rm $(DOCKER_IMAGE) bash /opt/hydra/docker-smoke-test.sh
	@echo "$(GREEN)Smoke test passed$(RESET)"
