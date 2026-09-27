CONFIG ?= config.toml

CONTAINER := $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)
IMAGE := lkml-ground-truth

# Run containers as the invoking user, never as root.
# Rootless Podman uses keep-id; Docker uses --user.
ifneq ($(CONTAINER),)
ifeq ($(shell $(CONTAINER) --version 2>/dev/null | grep -ci podman),0)
USER_FLAGS := --user $(shell id -u):$(shell id -g)
else
USER_FLAGS := --userns=keep-id
endif
endif
RUN := $(CONTAINER) run --rm $(USER_FLAGS)

REPO_VOLUME ?= $(CURDIR)/resources/linux/repo
DATASET_VOLUME ?= $(CURDIR)/resources/dataset

LIST ?=
ANALYSIS ?= dataset_coverage
RESULTS_DIR ?= output/analysis
ANALYSIS_DIR := src/lkml_ground_truth/analysis

.PHONY: all
all: run

.PHONY: config
config:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Copying example_config.toml -> $(CONFIG)"; \
		cp example_config.toml $(CONFIG); \
		echo "==> Edit $(CONFIG) with paths for your environment before running."; \
	else \
		echo "==> $(CONFIG) already exists; nothing to do."; \
	fi

# Alvo interno: garante runtime, imagem e diretórios de volume.
# Os diretórios são criados AQUI, com o seu usuário. Se não existirem, o
# Docker os cria como root no host ao montar o volume.
.PHONY: _ensure-image
_ensure-image:
	@if [ -z "$(CONTAINER)" ]; then \
		echo "==> No container runtime (docker/podman) found in PATH."; \
		exit 1; \
	fi; \
	mkdir -p "$(REPO_VOLUME)" "$(DATASET_VOLUME)"; \
	if ! $(CONTAINER) image inspect $(IMAGE) >/dev/null 2>&1; then \
		echo "==> Image $(IMAGE) not found, building..."; \
		$(MAKE) rebuild; \
	fi

.PHONY: repo
repo:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Error: $(CONFIG) não encontrado. Rode 'make config' primeiro."; \
		exit 1; \
	fi
	@echo "==> Clonando/checando o repositório do kernel (pode levar bastante"; \
	echo "    tempo dependendo de 'repo.since' em $(CONFIG) -- rode em background"; \
	echo "    se preferir: nohup make repo &)..."; \
	if command -v uv >/dev/null 2>&1; then \
		echo "==> Found uv toolchain, running natively..."; \
		uv run lkml-ground-truth --config $(CONFIG) clone-repo --force; \
	else \
		echo "==> uv toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
		$(MAKE) _ensure-image || exit 1; \
		$(RUN) -it \
			-v $(CURDIR):/app \
			-v $(REPO_VOLUME):/app/resources/linux/repo \
			-v $(DATASET_VOLUME):/app/resources/dataset \
			$(IMAGE) \
			--config $(CONFIG) clone-repo --force; \
	fi

.PHONY: run
run:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Error: $(CONFIG) não encontrado. Rode 'make config' primeiro."; \
		exit 1; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		echo "==> Found uv toolchain, running natively..."; \
		uv run lkml-ground-truth --config $(CONFIG); \
	else \
		echo "==> uv toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
		$(MAKE) _ensure-image || exit 1; \
		$(RUN) -it \
			-v $(CURDIR):/app \
			-v $(REPO_VOLUME):/app/resources/linux/repo \
			-v $(DATASET_VOLUME):/app/resources/dataset \
			$(IMAGE) \
			--config $(CONFIG); \
	fi

.PHONY: test
test:
	@if command -v nox >/dev/null 2>&1; then \
		echo "==> Found Python Testing toolchain, running natively..."; \
		nox; \
	else \
		echo "==> Python Testing toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
		$(MAKE) _ensure-image || exit 1; \
		$(RUN) \
			-v $(CURDIR):/app \
			--entrypoint uvx \
			$(IMAGE) \
			nox; \
	fi

.PHONY: lint
lint:
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff check .; \
	else \
		echo "==> uv não encontrado, instale-o ou rode 'make test' via container."; \
	fi

.PHONY: fmt
fmt:
	uv run ruff format .

.PHONY: rebuild
rebuild:
	$(CONTAINER) build -t $(IMAGE) -f Dockerfile .

.PHONY: enrich
enrich:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Error: $(CONFIG) não encontrado. Rode 'make config' primeiro."; \
		exit 1; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		echo "==> Found uv toolchain, running natively..."; \
		uv run lkml-ground-truth --config $(CONFIG) enrich; \
	else \
		echo "==> uv toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
		$(MAKE) _ensure-image || exit 1; \
		$(RUN) -it \
			-v $(CURDIR):/app \
			$(IMAGE) \
			--config $(CONFIG) enrich; \
	fi

.PHONY: analysis
analysis:
	@$(MAKE) -C $(ANALYSIS_DIR) run REPO_ROOT="$(CURDIR)" CONFIG="$(abspath $(CONFIG))" \
		ANALYSIS="$(ANALYSIS)" LIST="$(if $(LIST),$(LIST),all)" \
		RESULTS_DIR="$(abspath $(RESULTS_DIR))"

.PHONY: clean
clean:
	@echo "==> Cleaning local artifacts..."
	@rm -rf .venv .cache .nox .ruff_cache .pytest_cache htmlcov .coverage
	@rm -rf __pycache__ **/__pycache__
