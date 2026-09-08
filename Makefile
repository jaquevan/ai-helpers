.PHONY: validate lint security scaffold help docs cluster-env \
	mlflow-poc7 mlflow-smoke mlflow-smoke-all mlflow-compare mlflow-pipeline \
	mlflow-standby mlflow-resume \
	langfuse-env langfuse-local-env langfuse-local-up langfuse-local-down langfuse-smoke \
	langfuse-deps langfuse-eval langfuse-compare langfuse-pipeline langfuse-benchmark \
	langfuse-verify \
	test-subskills test-subskills-mlflow \
	run-phase0 run-phase1-verify run-golden-baseline run-run-mode-matrix run-model-experiments \
	run-foundation-batch run-foundation-continue

cluster-env: ## Print export PATH for oc/node (eval "$(make cluster-env)")
	@echo 'export PATH="$(CURDIR)/.local/node/bin:$$PATH"'

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

validate: ## Run manifest and doc validation (same as CI)
	@bash scripts/validate-manifests.sh
	@bash scripts/validate-skills.sh
	@bash scripts/generate-plugins-md.sh
	@echo "Checking generated docs are up to date..."
	@if ! git diff --quiet PLUGINS.md README.md CONTRIBUTING-SKILLS.md \
		plugins/*/README.md plugins/*/*/README.md 2>/dev/null; then \
		echo "Error: Generated docs are out of date. Run 'make docs' and commit the result."; \
		exit 1; \
	fi

lint: ## Run skillsaw content linter (zero-install via uvx)
	@command -v uvx >/dev/null 2>&1 || { \
		echo "Error: uvx not found. Install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	@echo "Running skillsaw..."
	@uvx skillsaw lint .

security: ## Run AI Guardian security scan (zero-install via uvx)
	@command -v uvx >/dev/null 2>&1 || { \
		echo "Error: uvx not found. Install uv: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	@echo "Running AI Guardian..."
	@uvx ai-guardian scan plugins/ --exclude '**/eval/cases/**'

docs: ## Regenerate PLUGINS.md, README plugin table, and CONTRIBUTING-SKILLS.md
	@bash scripts/generate-plugins-md.sh

scaffold: ## Scaffold a new skill: make scaffold PLUGIN=pf-react SKILL=pf-my-skill
ifndef PLUGIN
	$(error PLUGIN is required. Usage: make scaffold PLUGIN=pf-react SKILL=pf-my-skill)
endif
ifndef SKILL
	$(error SKILL is required. Usage: make scaffold PLUGIN=pf-react SKILL=pf-my-skill)
endif
	@bash scripts/scaffold-skill.sh $(PLUGIN) $(SKILL)

# ── Eval Pipeline ───────────────────────────────────────────────────
# MLflow scripts/config remain for research reference, but are not active.

EVAL_SKILL = plugins/uxd-workshop/skills/uxd-prototype-evaluate
EVAL_SCRIPTS = $(EVAL_SKILL)/scripts
EVAL_TESTS = $(EVAL_SKILL)/tests
LANGFUSE_POC7_URI = https://langfuse-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com
LANGFUSE_LOCAL_PORT ?= 3100
LANGFUSE_LOCAL_URI = http://localhost:$(LANGFUSE_LOCAL_PORT)
LANGFUSE_LOCAL_ENV = docker/langfuse/.env
PYTHON_RUN = $(if $(wildcard .venv/bin/python),.venv/bin/python,$(if $(shell command -v uv 2>/dev/null),uv run python3,python3))

mlflow-poc7: ## Deprecated compatibility target; MLflow is not used
	@echo 'MLflow is retained for research only and is not used by the active pipeline.'

KEY ?=
URL ?=
SCORERS ?= pipeline-output
MODEL ?=
SKILLS ?=
EVAL_PROVIDER ?=
EVAL_PLATFORM ?=

langfuse-eval: ## Score eval artifacts locally and log quality to Langfuse
	@if [ -z "$(KEY)" ]; then echo "Usage: make langfuse-eval KEY=RHAISTRAT-1492"; exit 1; fi
	@if [ -d .artifacts/$(KEY)/eval ]; then ARTIFACTS=.artifacts/$(KEY)/eval; \
	elif [ -d .artifacts/$(KEY) ]; then ARTIFACTS=.artifacts/$(KEY); \
	else echo "Missing .artifacts/$(KEY) or .artifacts/$(KEY)/eval"; exit 1; fi; \
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/langfuse-eval.py \
		$$ARTIFACTS \
		--model $(if $(MODEL),$(MODEL),unknown) \
		--prototype-key $(KEY) \
		--scorers $(SCORERS)

mlflow-smoke: ## Deprecated compatibility alias for langfuse-eval
	@$(MAKE) langfuse-eval KEY=$(KEY) MODEL=$(MODEL) SCORERS=$(SCORERS) SKILLS="$(SKILLS)"

mlflow-smoke-all: ## All scorers: make mlflow-smoke-all KEY=RHAISTRAT-1492
	@$(MAKE) mlflow-smoke KEY=$(KEY) SCORERS=all MODEL=$(MODEL) SKILLS="$(SKILLS)"

langfuse-compare: ## Compare direct-API models on subskills
	@if [ -z "$(KEY)" ]; then echo "Usage: make langfuse-compare KEY=RHAISTRAT-1492 URL=<prototype-url>"; exit 1; fi
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/langfuse-compare-models.py \
		--key $(KEY) \
		--url $(URL) \
		--skills $(if $(SKILLS),$(SKILLS),eval-extract eval-classify eval-consistency eval-report) \
		--models $(if $(MODELS),$(MODELS),gpt-5.6-luna gpt-5.6-terra gpt-5.6-sol)

mlflow-compare: ## Deprecated compatibility alias for langfuse-compare
	@$(MAKE) langfuse-compare KEY=$(KEY) URL=$(URL) MODEL=$(MODEL)

langfuse-pipeline: ## Direct API pipeline with Langfuse: make langfuse-pipeline KEY=... URL=...
	@if [ -z "$(KEY)" ] || [ -z "$(URL)" ]; then \
		echo "Usage: make langfuse-pipeline KEY=RHAISTRAT-1492 URL=http://127.0.0.1:3000"; exit 1; fi
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/langfuse-trace-pipeline.py \
		--key $(KEY) --url $(URL) \
		$(if $(MODEL),--model $(MODEL),) \
		$(if $(EVAL_PROVIDER),--provider $(EVAL_PROVIDER),) \
		$(if $(EVAL_PLATFORM),--platform $(EVAL_PLATFORM),) \
		$(if $(ITERATE_FLAGS),--iterate-flags="$(ITERATE_FLAGS)",) \
		$(if $(EXPERIMENT),--experiment-label="$(EXPERIMENT)",)

mlflow-pipeline: ## Deprecated compatibility alias for langfuse-pipeline
	@$(MAKE) langfuse-pipeline KEY=$(KEY) URL=$(URL) MODEL=$(MODEL) EVAL_PROVIDER=$(EVAL_PROVIDER) EVAL_PLATFORM=$(EVAL_PLATFORM) ITERATE_FLAGS="$(ITERATE_FLAGS)" EXPERIMENT=$(EXPERIMENT)

langfuse-env: ## Export Langfuse env for UXDPOC7 (eval "$(make langfuse-env)")
	@echo 'export LANGFUSE_HOST=$(LANGFUSE_POC7_URI)'
	@echo 'export LANGFUSE_ENABLED=1'
	@echo 'export LANGFUSE_OBS_COST_PER_RUN=0.05'
	@echo '# Set keys from Langfuse UI (not committed):'
	@echo '# export LANGFUSE_PUBLIC_KEY=pk-lf-...'
	@echo '# export LANGFUSE_SECRET_KEY=sk-lf-...'

langfuse-local-env: ## Export Langfuse env for local Docker stack (eval "$(make langfuse-local-env)")
	@echo 'export LANGFUSE_HOST=$(LANGFUSE_LOCAL_URI)'
	@echo 'export LANGFUSE_ENABLED=1'
	@echo 'export LANGFUSE_OBS_COST_PER_RUN=0'
	@if [ -f $(LANGFUSE_LOCAL_ENV) ]; then \
		grep -E '^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=' $(LANGFUSE_LOCAL_ENV) | sed 's/LANGFUSE_INIT_PROJECT_PUBLIC_KEY=/export LANGFUSE_PUBLIC_KEY=/'; \
		grep -E '^LANGFUSE_INIT_PROJECT_SECRET_KEY=' $(LANGFUSE_LOCAL_ENV) | sed 's/LANGFUSE_INIT_PROJECT_SECRET_KEY=/export LANGFUSE_SECRET_KEY=/'; \
	else \
		echo 'export LANGFUSE_PUBLIC_KEY=pk-lf-local-uxd-eval'; \
		echo 'export LANGFUSE_SECRET_KEY=sk-lf-local-uxd-eval-secret'; \
		echo '# Run make langfuse-local-up first to create $(LANGFUSE_LOCAL_ENV)'; \
	fi

langfuse-local-up: ## Start Langfuse via Docker Compose (http://localhost:3100)
	@LANGFUSE_LOCAL_PORT=$(LANGFUSE_LOCAL_PORT) bash scripts/langfuse-local-up.sh

langfuse-local-down: ## Stop local Langfuse Docker stack
	@bash scripts/langfuse-local-down.sh

langfuse-deps: ## Install Python deps for Langfuse SDK (creates .venv)
	@python3 -m venv .venv
	@.venv/bin/pip install -q langfuse
	@echo "Use: source .venv/bin/activate  (or make langfuse-smoke uses .venv automatically)"

langfuse-benchmark: ## Phase 3 Langfuse matrix benchmark (4 cells → local Langfuse UI)
	@bash scripts/run-langfuse-benchmark.sh $(URL)

mlflow-standby: ## Scale cluster MLflow+Postgres to 0 (free capacity for Langfuse)
	@bash scripts/mlflow-standby.sh

mlflow-resume: ## Restore cluster MLflow+Postgres after standby
	@bash scripts/mlflow-resume.sh

langfuse-smoke: ## Langfuse SDK smoke trace (dry-run if keys unset)
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/langfuse_trace.py smoke

langfuse-verify: ## Verify Langfuse health/auth and emit a metadata-only smoke trace
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/verify-langfuse.py

ledger-smoke: ## Append test row to cost ledger from existing artifacts
	@if [ -z "$(KEY)" ]; then echo "Usage: make ledger-smoke KEY=RHAISTRAT-1492"; exit 1; fi
	@node $(EVAL_SCRIPTS)/log-cost-ledger.js --artifacts-dir=.artifacts/$(KEY)/eval --payload-file=docs/cost-experiments/fixtures/ledger-smoke-row.json

run-phase0: ## Deploy Langfuse + document CP0 (requires oc login)
	bash scripts/deploy-langfuse-ux-eval.sh

run-phase1-verify: ## Phase 1 instrumentation checks (ledger + langfuse smoke)
	@$(MAKE) langfuse-smoke
	@$(MAKE) ledger-smoke KEY=$(if $(KEY),$(KEY),RHAISTRAT-1492)
	@python3 scripts/backfill-cost-ledger.py

backfill-ledger: ## Backfill cost ledger from existing artifacts
	@python3 scripts/backfill-cost-ledger.py

run-golden-baseline: ## Phase 2: run golden Opus baselines (requires URL)
	@bash scripts/run-golden-baseline.sh $(KEY) $(URL)

run-foundation-batch: ## Foundation: fixtures + tiered probes + 2 pipeline runs
	@bash scripts/run-foundation-batch.sh

run-foundation-continue: ## Continue foundation (tiered probes + golden-a; SKIP_MATRIX=1 default)
	@bash scripts/run-foundation-continue.sh

run-run-mode-matrix: ## Phase 3: 4-cell run-mode matrix on RHAISTRAT-1492
	@bash scripts/run-run-mode-matrix.sh $(URL)

run-model-experiments: ## Phase 4: cheaper model compare matrix
	@bash scripts/run-model-experiments.sh $(KEY) $(URL)

run-file-diet-experiments: ## Phase 5: file diet and tier experiments
	@bash scripts/run-file-diet-experiments.sh $(KEY) $(URL)

fix-mlflow-pods: ## Restart MLflow deployments in ux-eval
	@bash scripts/fix-mlflow-ux-eval.sh

test-subskills: ## Run subskill validation tests against fixtures
	bash $(EVAL_TESTS)/run-script-tests.sh

test-subskills-mlflow: ## Subskill tests + MLflow: make test-subskills-mlflow KEY=RHAISTRAT-1492
	@$(MAKE) mlflow-smoke KEY=$(KEY) SCORERS="pipeline-output report-rendering script-tests" MODEL=$(MODEL)
