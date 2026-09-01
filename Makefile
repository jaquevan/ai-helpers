.PHONY: validate lint security scaffold help docs \
	mlflow-poc7 mlflow-smoke mlflow-smoke-all mlflow-compare mlflow-pipeline \
	test-subskills test-subskills-mlflow

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

# ── MLflow / Eval Pipeline ──────────────────────────────────────────
# Baseline: RHAISTRAT-1492 (rhoai MR 170). See docs/eval-environment-audit.md

EVAL_SKILL = plugins/uxd-workshop/skills/uxd-prototype-evaluate
EVAL_SCRIPTS = $(EVAL_SKILL)/scripts
EVAL_TESTS = $(EVAL_SKILL)/tests
MLFLOW_POC7_URI = https://mlflow-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com
PYTHON_RUN = $(if $(shell command -v uv 2>/dev/null),uv run python3,python3)

mlflow-poc7: ## Export MLflow env for UXDPOC7 cluster (eval "$(make mlflow-poc7)")
	@echo 'export MLFLOW_TRACKING_URI=$(MLFLOW_POC7_URI)'
	@echo 'export MLFLOW_EXPERIMENT_NAME=prototype-creator-eval'
	@echo 'export MLFLOW_CLAUDE_TRACING_ENABLED=true'
	@echo 'unset MLFLOW_TRACKING_AUTH'

KEY ?=
URL ?=
SCORERS ?= pipeline-output
MODEL ?= recommended-mix
SKILLS ?=

mlflow-smoke: ## Score eval artifacts: make mlflow-smoke KEY=RHAISTRAT-1492
	@if [ -z "$(KEY)" ]; then echo "Usage: make mlflow-smoke KEY=RHAISTRAT-1492"; exit 1; fi
	@if [ -d .artifacts/$(KEY)/eval ]; then ARTIFACTS=.artifacts/$(KEY)/eval; \
	elif [ -d .artifacts/$(KEY) ]; then ARTIFACTS=.artifacts/$(KEY); \
	else echo "Missing .artifacts/$(KEY) or .artifacts/$(KEY)/eval"; exit 1; fi; \
	echo "MLFLOW_TRACKING_URI=$${MLFLOW_TRACKING_URI:-$(MLFLOW_POC7_URI)}"; \
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/mlflow-trace-eval.py \
		$$ARTIFACTS \
		--model $(MODEL) \
		--prototype-key $(KEY) \
		--experiment uxd-prototype-evaluate \
		--scorers $(SCORERS) \
		$(if $(SKILLS),--skills $(SKILLS),)

mlflow-smoke-all: ## All scorers: make mlflow-smoke-all KEY=RHAISTRAT-1492
	@$(MAKE) mlflow-smoke KEY=$(KEY) SCORERS=all MODEL=$(MODEL) SKILLS="$(SKILLS)"

mlflow-compare: ## Compare models on subskills: make mlflow-compare KEY=RHAISTRAT-1492 URL=http://127.0.0.1:3000
	@if [ -z "$(KEY)" ]; then echo "Usage: make mlflow-compare KEY=RHAISTRAT-1492 URL=<prototype-url>"; exit 1; fi
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/mlflow-compare-models.py \
		--key $(KEY) \
		$(if $(URL),--url $(URL),) \
		--skills $(if $(SKILLS),$(SKILLS),eval-extract eval-classify eval-consistency eval-report) \
		--models $(if $(MODELS),$(MODELS),claude-sonnet-4-6 claude-sonnet-5)

mlflow-pipeline: ## Traced full eval-iterate run: make mlflow-pipeline KEY=RHAISTRAT-1492 URL=http://127.0.0.1:3000
	@if [ -z "$(KEY)" ] || [ -z "$(URL)" ]; then \
		echo "Usage: make mlflow-pipeline KEY=RHAISTRAT-1492 URL=http://127.0.0.1:3000"; exit 1; fi
	$(PYTHON_RUN) $(EVAL_SCRIPTS)/mlflow-trace-pipeline.py \
		--key $(KEY) --url $(URL) \
		--model $(if $(MODEL),$(MODEL),claude-opus-4-6) \
		$(if $(ITERATE_FLAGS),--iterate-flags="$(ITERATE_FLAGS)",)

test-subskills: ## Run subskill validation tests against fixtures
	bash $(EVAL_TESTS)/run-script-tests.sh

test-subskills-mlflow: ## Subskill tests + MLflow: make test-subskills-mlflow KEY=RHAISTRAT-1492
	@$(MAKE) mlflow-smoke KEY=$(KEY) SCORERS="pipeline-output report-rendering script-tests" MODEL=$(MODEL)
