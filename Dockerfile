FROM python:3.12-slim

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libgit2-dev \
    && rm -rf /var/lib/apt/lists/*

# Instala o uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Cria usuário com o mesmo UID/GID do host
RUN groupadd -g ${GROUP_ID} app \
 && useradd -m -u ${USER_ID} -g ${GROUP_ID} app

WORKDIR /app

COPY . .

RUN chown -R app:app /app

RUN uv sync

ENV PATH="/opt/venv/bin:$PATH"

USER app

ENTRYPOINT ["lkml-ground-truth"]
