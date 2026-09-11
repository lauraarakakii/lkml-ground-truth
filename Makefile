# Variáveis de runtime do pipeline (sobrepõem o que está em config.toml
# apontando o processo pra outro arquivo de config, se necessário)
CONFIG ?= config.toml

# Detecção de runtime de container (docker ou podman), como no
# containers.mk do MailingListsHeritage
CONTAINER := $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)
IMAGE := lkml-ground-truth

REPO_VOLUME ?= $(CURDIR)/resources/linux/repo
DATASET_VOLUME ?= $(CURDIR)/resources/dataset

[FORMAT=csv]
SQL ?=
LIST ?=
OUTPUT ?=
FORMAT ?=
QUERY_ARGS  :=(if $(LIST),--list $(LIST),) \
			  (if $(OUTPUT),--output $(OUTPUT),) \
			  (if $(FORMAT),--format $(FORMAT),) 

.PHONY: all
all: run

.PHONY: config
config:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Copiando example_config.toml -> $(CONFIG)"; \
		cp example_config.toml $(CONFIG); \
		echo "==> Edite $(CONFIG) com os caminhos do seu ambiente antes de rodar."; \
	else \
		echo "==> $(CONFIG) já existe, nada a fazer."; \
	fi

# Alvo interno (não chame direto): garante que a imagem exista antes de
# qualquer target que rode via container, construindo-a se necessário.
.PHONY: _ensure-image
_ensure-image:
	@if [ -z "$(CONTAINER)" ]; then \
		echo "==> Nenhum runtime de container (docker/podman) encontrado no PATH."; \
		exit 1; \
	fi; \
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
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
			-v $(REPO_VOLUME):/app/resources/linux/repo \
    		-v $(DATASET_VOLUME):/app/resources/dataset \
			-w /app \
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
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
		    -v /resources/linux/repo:/app/resources/linux/repo \
			-v /media/discao/codev/analysis.laura/MLH-archiver/output/parser/dataset:/app/resources/dataset \
			-w /app \
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
		$(CONTAINER) run --rm \
			-v $(CURDIR):/app \
			-w /app \
			$(IMAGE) \
			uvx nox; \
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
	$(CONTAINER) build \
		--build-arg USER_ID=$(shell id -u) \
		--build-arg GROUP_ID=$(shell id -g) \
		-t $(IMAGE) \
		-f Dockerfile .

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
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
			-w /app \
			$(IMAGE) \
			--config $(CONFIG) enrich; \
	fi

.PHONY: query
query:
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "==> Error: $(CONFIG) não encontrado. Rode 'make config' primeiro."; \
		exit 1; \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		echo "==> Found uv toolchain, running natively..."; \
		uv run lkml-ground-truth --config $(CONFIG) query $(if $(SQL),"$(SQL)") $(QUERY_ARGS); \
	else \
		echo "==> uv toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
		$(MAKE) _ensure-image || exit 1; \
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
			-V $(DATASET_VOLUME):/app/resources/dataset \
			-w /app \
			$(IMAGE) \
			--config $(CONFIG) query $(if $(SQL),"$(SQL)") $(QUERY_ARGS); \
	fi

.PHONY: clean
clean:
	@echo "==> Limpando artefatos locais..."
	@rm -rf .venv .cache .nox .ruff_cache .pytest_cache htmlcov .coverage
	@rm -rf __pycache__ **/__pycache__