FROM python:3.12-slim AS builder

ARG USER_ID=1000
ARG GROUP_ID=1000

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_CACHE=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked

FROM python:3.12-slim AS runtime

ARG USER_ID=1000
ARG GROUP_ID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g ${GROUP_ID} app \
&& useradd -m -u ${USER_ID} -g ${GROUP_ID} app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

ENV PATH="/opt/venv/bin:$PATH"

USER app

ENTRYPOINT ["lkml-ground-truth"]