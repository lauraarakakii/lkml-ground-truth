REPO_ROOT ?= $(abspath $(CURDIR)/../../..)
CONFIG ?= $(REPO_ROOT)/config.toml
RESULTS_DIR ?= $(REPO_ROOT)/output/analysis
ANALYSIS ?= dataset_coverage
LIST ?= all
SQL ?=
OUTPUT ?=
FORMAT ?=
LIMIT ?= 20

RESULT_FILE := $(RESULTS_DIR)/$(ANALYSIS).csv

.PHONY: help
help:
	@echo "Use: make -C src/lkml_ground_truth/analysis run ANALYSIS=<name> [LIST=<list>]"
	@echo "     make -C src/lkml_ground_truth/analysis query [SQL='SELECT ...'] [LIST=<list>]"
	@echo "Available analyses: commit_reuse, dataset_coverage, match_coverage, match_errors, score_bands, matched_pairs"

.PHONY: query
query:
	@if command -v uv >/dev/null 2>&1; then \
		cd "$(REPO_ROOT)" && uv run python -m lkml_ground_truth.analysis.sql_querier --config "$(CONFIG)" \
			$(if $(SQL),"$(SQL)") $(if $(LIST),--list "$(LIST)") \
			$(if $(OUTPUT),--output "$(OUTPUT)") $(if $(FORMAT),--format "$(FORMAT)") \
			--limit "$(LIMIT)"; \
	else \
		echo "==> uv is required to run analysis queries."; \
		exit 1; \
	fi

.PHONY: run
run:
	@mkdir -p "$(RESULTS_DIR)"
	@cd "$(REPO_ROOT)" && uv run python -m lkml_ground_truth.analysis.run \
		--config "$(CONFIG)" --analysis "$(ANALYSIS)" --list "$(LIST)" \
		--output "$(RESULT_FILE)"
	@echo "==> Result saved to $(RESULT_FILE)"
