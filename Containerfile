FROM python:3.12-slim AS builder

ARG USER_ID=1000
ARG GROUP_ID=1000

# pygit2 precisa de libgit2 + toolchain de build para compilar suas
# dependências nativas em algumas plataformas
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential libgit2-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala o uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . .

RUN uv sync --locked

ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["lkml-ground-truth"]
