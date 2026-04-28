# ============================================
# SciTeX Orochi - Hub Orchestrator
# ============================================
# Operations for the Django/Daphne hub at scitex-orochi.com.
# Modeled on scitex-cloud's Makefile (same conventions, same
# "ENV must be specified" discipline).
#
# Two environments live in deployment/docker/:
#   ENV=dev     → docker-compose.dev.yml      (port 8560, orochi-server-dev)
#   ENV=stable  → docker-compose.stable.yml   (port 8559, orochi-server-stable)
#
# Production = the `stable` container running on mba (Apple Silicon).
# Local development uses `dev` on the WSL workstation.
#
# Quick reference:
#   make status                          What's running, on which branch
#   make ENV=dev start                   Start dev container
#   make ENV=stable rebuild              Rebuild stable image (for code changes)
#   make ENV=stable logs                 Tail stable logs
#   make ENV=stable shell                Django shell in stable
#   make frontend-build                  Build the Vite TS bundle locally
#   make prod-deploy                     git push + ssh mba rebuild + cf purge
#   make prod-cf-purge                   Purge Cloudflare cache for orochi.com
#   make prod-screenshot                 Self-auth screenshot via playwright

SHELL := /bin/bash

.PHONY: \
	help \
	help-all \
	status \
	validate \
	validate-docker \
	start \
	stop \
	restart \
	down \
	build \
	build-no-cache \
	rebuild \
	rebuild-no-cache \
	logs \
	logs-follow \
	ps \
	shell \
	exec \
	migrate \
	makemigrations \
	collectstatic \
	createsuperuser \
	session \
	frontend-install \
	frontend-build \
	frontend-typecheck \
	frontend-clean \
	format \
	format-python \
	format-shell \
	lint \
	typecheck \
	test \
	clean \
	clean-python \
	clean-frontend \
	prod-deploy \
	prod-restart \
	prod-rebuild \
	prod-logs \
	prod-shell \
	prod-cf-purge \
	prod-screenshot \
	prod-session \
	dev-up \
	dev-down \
	dev-logs \
	check-host \
	info

.DEFAULT_GOAL := help

# ============================================
# Configuration
# ============================================
VALID_ENVS := dev stable

# Accept lowercase env= as alias for ENV=
ifdef env
  ENV := $(env)
endif

# Project paths
PROJECT_ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
DOCKER_DIR    := $(PROJECT_ROOT)/deployment/docker
FRONTEND_DIR  := $(PROJECT_ROOT)/hub/frontend

# Cloudflare zone for scitex-orochi.com
CF_ZONE_OROCHI := 2eda29d603d74180011e6711ffff65a3

# Production host (mba) — single source of truth
PROD_HOST := mba
PROD_REPO := ~/proj/scitex-orochi

# Colors
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
CYAN   := \033[0;36m
BLUE   := \033[0;34m
NC     := \033[0m

# ============================================
# Environment dispatch
# ============================================
# Each ENV maps to a compose file + container name.
ifdef ENV
  ifeq ($(filter $(ENV),$(VALID_ENVS)),)
    $(error Invalid ENV='$(ENV)'. Must be one of: $(VALID_ENVS))
  endif
  COMPOSE_FILE := $(DOCKER_DIR)/docker-compose.$(ENV).yml
  ifeq ($(ENV),dev)
    CONTAINER := orochi-server-dev
  else
    CONTAINER := orochi-server-stable
  endif
  COMPOSE := docker compose -f $(COMPOSE_FILE)
else
  # Targets allowed without ENV (don't touch a specific compose file)
  ENV_NOT_REQUIRED := help help-all status validate validate-docker \
                      frontend-install frontend-build frontend-typecheck \
                      frontend-clean format format-python format-shell \
                      lint typecheck test clean clean-python clean-frontend \
                      prod-deploy prod-restart prod-rebuild prod-logs \
                      prod-shell prod-cf-purge prod-screenshot prod-session \
                      check-host info
  ifneq ($(MAKECMDGOALS),)
    ifneq ($(filter-out $(ENV_NOT_REQUIRED),$(MAKECMDGOALS)),)
      $(error ENV not specified. Use: make ENV=<dev|stable> <target>)
    endif
  endif
endif

# ============================================
# Help (default)
# ============================================
help:
	@echo -e ""
	@echo -e "$(GREEN)SciTeX Orochi$(NC) - Hub: $(CYAN)dev$(NC) | $(CYAN)stable$(NC)"
	@echo -e ""
	@echo -e "$(CYAN)Common:$(NC)"
	@echo -e "  make status                     Container + branch state"
	@echo -e "  make ENV=<env> start            Start container"
	@echo -e "  make ENV=<env> rebuild          Rebuild image (after code changes)"
	@echo -e "  make ENV=<env> logs             Container logs (last 200 lines)"
	@echo -e "  make ENV=<env> shell            Django shell"
	@echo -e ""
	@echo -e "$(CYAN)Frontend:$(NC)"
	@echo -e "  make frontend-build             Build Vite TS bundle"
	@echo -e "  make frontend-typecheck         tsc --noEmit"
	@echo -e ""
	@echo -e "$(CYAN)Production (mba):$(NC)"
	@echo -e "  make prod-deploy                git push + remote rebuild + CF purge"
	@echo -e "  make prod-cf-purge              Purge Cloudflare cache"
	@echo -e "  make prod-screenshot            Self-auth playwright screenshot"
	@echo -e ""
	@echo -e "  make help-all                   Full target list"
	@echo -e ""

# ============================================
# Help (full)
# ============================================
help-all:
	@echo -e ""
	@echo -e "$(GREEN)╔══════════════════════════════════════════════════╗$(NC)"
	@echo -e "$(GREEN)║   SciTeX Orochi - Full Target Reference          ║$(NC)"
	@echo -e "$(GREEN)╚══════════════════════════════════════════════════╝$(NC)"
	@echo -e ""
	@echo -e "$(CYAN)Status / inspection$(NC)"
	@echo -e "  status                          Container + branch state"
	@echo -e "  validate                        Sanity-check docker availability"
	@echo -e "  info                            Project paths + versions"
	@echo -e "  check-host                      Verify expected hostname"
	@echo -e ""
	@echo -e "$(CYAN)Container lifecycle (ENV=dev|stable)$(NC)"
	@echo -e "  ENV=<env> start                 docker compose up -d"
	@echo -e "  ENV=<env> stop                  docker compose stop"
	@echo -e "  ENV=<env> restart               docker compose restart"
	@echo -e "  ENV=<env> down                  docker compose down"
	@echo -e "  ENV=<env> build                 docker compose build"
	@echo -e "  ENV=<env> build-no-cache        docker compose build --no-cache"
	@echo -e "  ENV=<env> rebuild               build + up -d (after code changes)"
	@echo -e "  ENV=<env> rebuild-no-cache      build --no-cache + up -d"
	@echo -e ""
	@echo -e "$(CYAN)Inspection (ENV=dev|stable)$(NC)"
	@echo -e "  ENV=<env> logs                  Container logs (last 200 lines)"
	@echo -e "  ENV=<env> logs-follow           Tail logs live"
	@echo -e "  ENV=<env> ps                    docker compose ps"
	@echo -e "  ENV=<env> shell                 Django shell"
	@echo -e "  ENV=<env> exec CMD='...'        Run arbitrary command in container"
	@echo -e ""
	@echo -e "$(CYAN)Django (ENV=dev|stable)$(NC)"
	@echo -e "  ENV=<env> migrate               Apply schema migrations"
	@echo -e "  ENV=<env> makemigrations        Create migration files"
	@echo -e "  ENV=<env> collectstatic         Collect static files (incl. hashed)"
	@echo -e "  ENV=<env> createsuperuser       Create admin user (interactive)"
	@echo -e "  ENV=<env> session               Mint a sessionid for self-auth"
	@echo -e ""
	@echo -e "$(CYAN)Frontend (no ENV)$(NC)"
	@echo -e "  frontend-install                npm install in hub/frontend/"
	@echo -e "  frontend-build                  npm run build (Vite ES bundle)"
	@echo -e "  frontend-typecheck              tsc --noEmit"
	@echo -e "  frontend-clean                  Remove dist/ + node_modules/"
	@echo -e ""
	@echo -e "$(CYAN)Quality (no ENV)$(NC)"
	@echo -e "  format                          ruff + shfmt"
	@echo -e "  format-python                   ruff format src/ hub/ orochi/ tests/"
	@echo -e "  format-shell                    shfmt scripts/ deployment/"
	@echo -e "  lint                            ruff check"
	@echo -e "  typecheck                       pyright"
	@echo -e "  test                            pytest"
	@echo -e ""
	@echo -e "$(CYAN)Cleanup (no ENV)$(NC)"
	@echo -e "  clean                           clean-python + clean-frontend"
	@echo -e "  clean-python                    Remove __pycache__, *.pyc, .pytest_cache"
	@echo -e "  clean-frontend                  Remove dist/, node_modules/"
	@echo -e ""
	@echo -e "$(CYAN)Production (mba)$(NC)"
	@echo -e "  prod-deploy                     git push + ssh mba rebuild + CF purge"
	@echo -e "  prod-rebuild                    ssh mba rebuild only (no git push)"
	@echo -e "  prod-restart                    ssh mba restart container (no rebuild)"
	@echo -e "  prod-logs                       Tail stable container logs on mba"
	@echo -e "  prod-shell                      Django shell on mba stable container"
	@echo -e "  prod-cf-purge                   Purge Cloudflare cache for scitex-orochi.com"
	@echo -e "  prod-session                    Mint a sessionid on mba (for screenshot)"
	@echo -e "  prod-screenshot                 playwright screenshot of dashboard"
	@echo -e ""

# ============================================
# Status
# ============================================
status:
	@echo -e ""
	@echo -e "$(CYAN)Local containers:$(NC)"
	@docker ps --filter 'name=orochi-server' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "  docker not running locally"
	@echo -e ""
	@echo -e "$(CYAN)Local git:$(NC)"
	@git -C $(PROJECT_ROOT) status -sb | head -5
	@echo -e ""
	@echo -e "$(CYAN)Production (mba):$(NC)"
	@ssh -o ConnectTimeout=3 $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		git -C $(PROD_REPO) log --oneline -1; \
		docker ps --filter "name=orochi-server-stable" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"' 2>/dev/null \
		|| echo "  mba unreachable"
	@echo -e ""

# ============================================
# Validation
# ============================================
validate-docker:
	@docker ps >/dev/null 2>&1 || (echo -e "$(RED)docker daemon not running$(NC)"; exit 1)

validate: validate-docker

# ============================================
# Container lifecycle
# ============================================
start: validate-docker
	@echo -e "$(CYAN)Starting $(CONTAINER) ($(ENV))…$(NC)"
	$(COMPOSE) up -d
	@echo -e "$(GREEN)up$(NC)"

stop: validate-docker
	$(COMPOSE) stop

down: validate-docker
	$(COMPOSE) down

restart: validate-docker
	$(COMPOSE) restart

build: validate-docker
	@echo -e "$(CYAN)Building $(CONTAINER) image…$(NC)"
	$(COMPOSE) build

build-no-cache: validate-docker
	$(COMPOSE) build --no-cache

rebuild: validate-docker
	@echo -e "$(CYAN)Rebuilding $(CONTAINER) (build + up -d)…$(NC)"
	$(COMPOSE) build
	$(COMPOSE) up -d
	@echo -e "$(GREEN)rebuilt$(NC)"

rebuild-no-cache: validate-docker
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

# ============================================
# Inspection
# ============================================
logs: validate-docker
	$(COMPOSE) logs --tail=200

logs-follow: validate-docker
	$(COMPOSE) logs -f

ps: validate-docker
	$(COMPOSE) ps

shell: validate-docker
	docker exec -it $(CONTAINER) python manage.py shell

# Usage: make ENV=stable exec CMD='ls -la /app'
exec: validate-docker
	@if [ -z "$(CMD)" ]; then \
		echo -e "$(RED)CMD required: make ENV=$(ENV) exec CMD='your-command'$(NC)"; \
		exit 1; \
	fi
	docker exec -it $(CONTAINER) sh -c "$(CMD)"

# ============================================
# Django
# ============================================
migrate: validate-docker
	docker exec $(CONTAINER) python manage.py migrate

makemigrations: validate-docker
	docker exec $(CONTAINER) python manage.py makemigrations

collectstatic: validate-docker
	docker exec $(CONTAINER) python manage.py collectstatic --noinput

createsuperuser: validate-docker
	docker exec -it $(CONTAINER) python manage.py createsuperuser

# Mint a sessionid for the first superuser. Print to stdout so callers
# can capture and inject into curl/playwright. Used by prod-screenshot.
session: validate-docker
	@docker exec $(CONTAINER) python manage.py shell -c "\
from django.contrib.auth import get_user_model;\
from django.contrib.sessions.backends.db import SessionStore;\
U = get_user_model();\
u = U.objects.filter(is_superuser=True).first() or U.objects.first();\
s = SessionStore();\
s['_auth_user_id'] = str(u.id);\
s['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend';\
s['_auth_user_hash'] = u.get_session_auth_hash();\
s.create();\
print(s.session_key)" 2>/dev/null | tail -1

# ============================================
# Frontend (Vite TS bundle)
# ============================================
frontend-install:
	cd $(FRONTEND_DIR) && npm install --no-audit --no-fund

frontend-build:
	@if [ ! -d "$(FRONTEND_DIR)/node_modules" ]; then \
		echo -e "$(YELLOW)node_modules missing — running install first$(NC)"; \
		$(MAKE) frontend-install; \
	fi
	cd $(FRONTEND_DIR) && npm run build

frontend-typecheck:
	cd $(FRONTEND_DIR) && npm run typecheck

frontend-clean:
	rm -rf $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/dist \
	       $(PROJECT_ROOT)/hub/static/hub/dist

# ============================================
# Quality
# ============================================
format: format-python format-shell

format-python:
	@command -v ruff >/dev/null 2>&1 || (echo -e "$(RED)ruff not installed$(NC)"; exit 1)
	cd $(PROJECT_ROOT) && ruff format src/ hub/ orochi/ tests/ scripts/

format-shell:
	@command -v shfmt >/dev/null 2>&1 || (echo -e "$(YELLOW)shfmt not installed — skipping$(NC)"; exit 0)
	find $(PROJECT_ROOT)/scripts $(PROJECT_ROOT)/deployment \
		-name '*.sh' -type f -exec shfmt -i 4 -w {} +

lint:
	@command -v ruff >/dev/null 2>&1 || (echo -e "$(RED)ruff not installed$(NC)"; exit 1)
	cd $(PROJECT_ROOT) && ruff check src/ hub/ orochi/ tests/

# CSS cascade-trap audit. Catches the `.avatar-clickable`/<td> family of
# bugs (2026-04-27 incident: a class declaring `display: inline-flex`
# was applied to a <td>, knocking it out of `display: table-cell` and
# silently nullifying `vertical-align: middle`). Runs in <1 s; safe to
# wire into pre-commit. Zero deps beyond Python stdlib + ripgrep/grep.
lint-css:
	cd $(PROJECT_ROOT) && python3 scripts/server/lint-css-cascade-traps.py

# Bundle-size budget for the Vite-built JS bundle. Caps the largest
# `hub/static/hub/dist/orochi-*.js` at 1024 KB ungzipped (current is
# ~770 KB). Bump the limit when an intentional addition pushes it
# over; refuse silent bloat. See EI-2026-04-28 §6.
BUNDLE_BUDGET_KB := 1024
# 30-second hub-flap diagnostic chain. Walks the same probe sequence
# that took 30 minutes to derive during the 2026-04-27 incident: edge
# vs origin vs port-binder identity vs lima clock-jump vs cloudflared
# health vs Daphne process vs Django error rate. Read-only — prints a
# verdict per check and an actionable summary. See EI-2026-04-28 §5.
diagnose-hub:
	cd $(PROJECT_ROOT) && bash scripts/server/diagnose-hub.sh $(PROD_HOST)

lint-bundle-size:
	@cd $(PROJECT_ROOT) && \
		bundle=$$(ls hub/static/hub/dist/orochi-*.js 2>/dev/null | head -1); \
		if [ -z "$$bundle" ]; then \
			echo -e "$(YELLOW)no bundle found — run 'cd hub/frontend && npm run build'$(NC)"; \
			exit 0; \
		fi; \
		size_kb=$$(du -k "$$bundle" | awk '{print $$1}'); \
		if [ "$$size_kb" -gt "$(BUNDLE_BUDGET_KB)" ]; then \
			echo -e "$(RED)✗ bundle $$bundle is $${size_kb}KB > budget $(BUNDLE_BUDGET_KB)KB$(NC)"; \
			echo -e "    Either reduce the bundle (vite-bundle-visualizer) or"; \
			echo -e "    bump BUNDLE_BUDGET_KB in the Makefile with a comment"; \
			echo -e "    explaining why."; \
			exit 1; \
		fi; \
		echo -e "$(GREEN)✓ bundle $${size_kb}KB ≤ budget $(BUNDLE_BUDGET_KB)KB$(NC)"

typecheck:
	@command -v pyright >/dev/null 2>&1 || (echo -e "$(RED)pyright not installed$(NC)"; exit 1)
	cd $(PROJECT_ROOT) && pyright

test:
	@command -v pytest >/dev/null 2>&1 || (echo -e "$(RED)pytest not installed$(NC)"; exit 1)
	cd $(PROJECT_ROOT) && pytest tests/

# ============================================
# Cleanup
# ============================================
clean: clean-python clean-frontend

clean-python:
	find $(PROJECT_ROOT) -type d -name '__pycache__' -prune -exec rm -rf {} +
	find $(PROJECT_ROOT) -type f -name '*.pyc' -delete
	rm -rf $(PROJECT_ROOT)/.pytest_cache $(PROJECT_ROOT)/.ruff_cache

clean-frontend: frontend-clean

# ============================================
# Production (mba)
# ============================================
# prod-deploy is the canonical "ship it" recipe. Tier 2 deploy:
# rebuild image with cache, restart container, purge Cloudflare.
# For Tier 1 fast-cp deploys see deploy-strategy memory.
prod-deploy:
	@echo -e "$(CYAN)Pushing develop to origin…$(NC)"
	git -C $(PROJECT_ROOT) push origin $$(git -C $(PROJECT_ROOT) branch --show-current)
	@$(MAKE) prod-rebuild
	@$(MAKE) prod-cf-purge
	@echo -e "$(GREEN)deployed$(NC)"

# Tier-1 fast-cp deploy: copy a single repo-relative file into the
# running container, run collectstatic so the hashed-static layer
# picks it up, and purge Cloudflare. ~5 s wall-clock vs. 30 s for
# Tier-2 prod-deploy. Use for CSS / template / single-source-file
# fixes; for code changes that affect Python imports prefer prod-deploy.
#   make prod-hot-cp FILE=hub/static/hub/components/components-agent-cards.css
#   make prod-hot-cp FILE=hub/templates/hub/dashboard.html
prod-hot-cp:
	@if [ -z "$(FILE)" ]; then \
		echo -e "$(RED)FILE=<repo-relative path> required$(NC)"; \
		echo -e "  example: make prod-hot-cp FILE=hub/static/hub/style/style-base.css"; \
		exit 64; \
	fi
	@if [ ! -f "$(PROJECT_ROOT)/$(FILE)" ]; then \
		echo -e "$(RED)$(FILE) not found in repo$(NC)"; \
		exit 65; \
	fi
	@echo -e "$(CYAN)hot-cp $(FILE) → $(PROD_HOST):/app/$(FILE)$(NC)"
	@cat "$(PROJECT_ROOT)/$(FILE)" | \
		ssh $(PROD_HOST) "source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
			docker exec -i orochi-server-stable sh -c 'cat > /app/$(FILE)'"
	@if echo "$(FILE)" | grep -q "^hub/static/"; then \
		echo -e "$(CYAN)collectstatic (hashed-static layer)…$(NC)"; \
		ssh $(PROD_HOST) "source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
			docker exec orochi-server-stable python manage.py collectstatic --noinput 2>&1 | tail -2"; \
	fi
	@$(MAKE) prod-cf-purge
	@echo -e "$(GREEN)hot-cp deployed$(NC)"

prod-rebuild:
	@echo -e "$(CYAN)Rebuilding stable image on $(PROD_HOST)…$(NC)"
	ssh $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		git -C $(PROD_REPO) pull --ff-only origin $$(git -C $(PROD_REPO) branch --show-current) && \
		cd $(PROD_REPO) && \
		docker compose -f deployment/docker/docker-compose.stable.yml up -d --build'
	@echo -e "$(GREEN)rebuilt$(NC)"

prod-restart:
	@echo -e "$(CYAN)Restarting stable container on $(PROD_HOST) (no rebuild)…$(NC)"
	ssh $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		docker restart orochi-server-stable'

prod-logs:
	ssh $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		docker logs --tail=200 orochi-server-stable'

prod-shell:
	ssh -t $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		docker exec -it orochi-server-stable python manage.py shell'

# Purge Cloudflare cache for scitex-orochi.com.
# Requires SCITEX_CLOUDFLARE_EMAIL + SCITEX_CLOUDFLARE_API_KEY in env
# (sourced from ~/.dotfiles/src/.bash.d/secrets/).
prod-cf-purge:
	@if [ -z "$$SCITEX_CLOUDFLARE_API_KEY" ] || [ -z "$$SCITEX_CLOUDFLARE_EMAIL" ]; then \
		echo -e "$(RED)SCITEX_CLOUDFLARE_API_KEY / EMAIL not set in env$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(CYAN)Purging Cloudflare cache for scitex-orochi.com…$(NC)"
	@curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$(CF_ZONE_OROCHI)/purge_cache" \
		-H "X-Auth-Email: $$SCITEX_CLOUDFLARE_EMAIL" \
		-H "X-Auth-Key: $$SCITEX_CLOUDFLARE_API_KEY" \
		-H "Content-Type: application/json" \
		--data '{"purge_everything":true}' | head -c 200
	@echo ""
	@echo -e "$(GREEN)purged$(NC)"

# Fleet-wide ``pip install -U scitex-orochi`` across every host listed
# in orochi-machines.yaml. Use after a producer-side dependency change
# (e.g. detect-secrets in 0.15.6) so the new collector reaches every
# agent. Idempotent — pip is a no-op when already current.
#   make fleet-agents-upgrade               # all hosts
#   make fleet-agents-upgrade ARGS=--dry-run
#   make fleet-agents-upgrade ARGS="--hosts mba,nas"
fleet-agents-upgrade:
	cd $(PROJECT_ROOT) && bash scripts/server/fleet-agents-upgrade.sh $(ARGS)

# Mint a fresh sessionid on the mba stable container — used by
# prod-screenshot for self-auth without going through SSO.
prod-session:
	@ssh $(PROD_HOST) 'source ~/.zprofile 2>/dev/null; source ~/.zshrc 2>/dev/null; \
		docker exec orochi-server-stable python manage.py shell -c "\
from django.contrib.auth import get_user_model;\
from django.contrib.sessions.backends.db import SessionStore;\
U = get_user_model();\
u = U.objects.filter(is_superuser=True).first() or U.objects.first();\
s = SessionStore();\
s[\"_auth_user_id\"] = str(u.id);\
s[\"_auth_user_backend\"] = \"django.contrib.auth.backends.ModelBackend\";\
s[\"_auth_user_hash\"] = u.get_session_auth_hash();\
s.create();\
print(s.session_key)" 2>/dev/null | tail -1'

# Screenshot the prod dashboard via playwright-cli with self-auth.
# Output: /tmp/orochi-prod-screenshot.png
prod-screenshot:
	@command -v playwright-cli >/dev/null 2>&1 || (echo -e "$(RED)playwright-cli not installed$(NC)"; exit 1)
	@SESSION=$$($(MAKE) -s prod-session); \
		if [ -z "$$SESSION" ]; then echo -e "$(RED)no session$(NC)"; exit 1; fi; \
		echo -e "$(CYAN)session: $$SESSION$(NC)"; \
		playwright-cli -s=orochi-make open about:blank >/dev/null 2>&1 || true; \
		playwright-cli -s=orochi-make cookie-set sessionid $$SESSION \
			--domain=.scitex-orochi.com --httpOnly --secure >/dev/null; \
		playwright-cli -s=orochi-make resize 1920 1080 >/dev/null; \
		playwright-cli -s=orochi-make goto https://scitex-lab.scitex-orochi.com/ >/dev/null; \
		sleep 4; \
		playwright-cli -s=orochi-make screenshot \
			--filename=/tmp/orochi-prod-screenshot.png; \
		echo -e "$(GREEN)→ /tmp/orochi-prod-screenshot.png$(NC)"

# ============================================
# Convenience aliases for the most common dev flow
# ============================================
dev-up:    ; $(MAKE) ENV=dev start
dev-down:  ; $(MAKE) ENV=dev down
dev-logs:  ; $(MAKE) ENV=dev logs

# ============================================
# Misc
# ============================================
check-host:
	@HOST=$$(hostname); \
		if [ "$$HOST" = "ywata-note-win" ]; then \
			echo -e "$(GREEN)host: $$HOST (WSL workstation)$(NC)"; \
		elif [ "$$HOST" = "mba" ] || [ "$$HOST" = "mba.local" ]; then \
			echo -e "$(GREEN)host: $$HOST (production)$(NC)"; \
		else \
			echo -e "$(YELLOW)host: $$HOST (unrecognized)$(NC)"; \
		fi

info:
	@echo -e "$(CYAN)Project:$(NC)     SciTeX Orochi"
	@echo -e "$(CYAN)Root:$(NC)        $(PROJECT_ROOT)"
	@echo -e "$(CYAN)Frontend:$(NC)    $(FRONTEND_DIR)"
	@echo -e "$(CYAN)Docker dir:$(NC)  $(DOCKER_DIR)"
	@echo -e "$(CYAN)Branch:$(NC)      $$(git -C $(PROJECT_ROOT) branch --show-current)"
	@echo -e "$(CYAN)Python:$(NC)      $$(python3 --version 2>&1)"
	@echo -e "$(CYAN)Node:$(NC)        $$(node --version 2>/dev/null || echo not installed)"
	@echo -e "$(CYAN)Docker:$(NC)      $$(docker --version 2>/dev/null || echo not installed)"
