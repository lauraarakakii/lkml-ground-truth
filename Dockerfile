FROM python:3.12-slim

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
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY . .

# Usa uv.lock se ele já existir no repo (build reprodutível, é o caso
# normal); se não existir por algum motivo, uv gera um na hora -- essa
# imagem de conveniência não deve travar por causa disso.
RUN uv sync

ENV PATH="/opt/venv/bin:$PATH"

ENTRYPOINT ["lkml-ground-truth"]
