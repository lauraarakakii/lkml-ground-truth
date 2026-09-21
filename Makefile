CONFIG ?= config.toml

CONTAINER := $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)
IMAGE := lkml-ground-truth

# Roda o container com o UID/GID de quem invocou o make (nunca root).
# Podman rootless: keep-id mapeia o seu usuário direto. Docker: --user.
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

SQL ?=
LIST ?=
OUTPUT ?=
FORMAT ?=
QUERY_ARGS := $(if $(LIST),--list $(LIST)) \
              $(if $(OUTPUT),--output $(OUTPUT)) \
              $(if $(FORMAT),--format $(FORMAT))

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

# Alvo interno: garante runtime, imagem e diretórios de volume.
# Os diretórios são criados AQUI, com o seu usuário. Se não existirem, o
# Docker os cria como root no host ao montar o volume.
.PHONY: _ensure-image
_ensure-image:
	@if [ -z "$(CONTAINER)" ]; then \
		echo "==> Nenhum runtime de container (docker/podman) encontrado no PATH."; \
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
		$(RUN) -it \
			-v $(CURDIR):/app \
			-v $(DATASET_VOLUME):/app/resources/dataset \
			$(IMAGE) \
			--config $(CONFIG) query $(if $(SQL),"$(SQL)") $(QUERY_ARGS); \
	fi

.PHONY: clean
clean:
	@echo "==> Limpando artefatos locais..."
	@rm -rf .venv .cache .nox .ruff_cache .pytest_cache htmlcov .coverage
	@rm -rf __pycache__ **/__pycache__