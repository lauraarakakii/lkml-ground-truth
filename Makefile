# Variáveis de runtime do pipeline (sobrepõem o que está em config.toml
# apontando o processo pra outro arquivo de config, se necessário)
CONFIG ?= config.toml

# Detecção de runtime de container (docker ou podman), como no
# containers.mk do MailingListsHeritage
CONTAINER := $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)
IMAGE := lkml-ground-truth
IMAGE_EXISTS := $(shell $(CONTAINER) image inspect $(IMAGE) >/dev/null 2>&1 && echo yes || echo no)

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
		uv run lkml-ground-truth --config $(CONFIG) clone-repo --force; \
	else \
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
			-w /app \
			$(IMAGE) \
			lkml-ground-truth --config $(CONFIG) clone-repo --force; \
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
		if [ "$(IMAGE_EXISTS)" = "no" ]; then \
			echo "==> Image $(IMAGE) not found, building..."; \
			$(MAKE) rebuild; \
		fi; \
		$(CONTAINER) run --rm -it \
			-v $(CURDIR):/app \
			-w /app \
			$(IMAGE) \
			lkml-ground-truth --config $(CONFIG); \
	fi

.PHONY: test
test:
	@if command -v nox >/dev/null 2>&1; then \
		echo "==> Found Python Testing toolchain, running natively..."; \
		nox; \
	else \
		echo "==> Python Testing toolchain not found, running with $(CONTAINER) (Image: $(IMAGE))..."; \
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
	$(CONTAINER) build --build-arg USER_ID=$(shell id -u) --build-arg GROUP_ID=$(shell id -g) -t $(IMAGE) -f Containerfile .

.PHONY: clean
clean:
	@echo "==> Limpando artefatos locais..."
	@rm -rf .venv .cache .nox .ruff_cache .pytest_cache htmlcov .coverage
	@rm -rf __pycache__ **/__pycache__
