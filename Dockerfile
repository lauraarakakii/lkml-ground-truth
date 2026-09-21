FROM python:3.12-slim AS builder

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

# Root só existe aqui, em build time (apt precisa dele)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # repos montados podem ter outro dono; evita "dubious ownership"
    && git config --system --add safe.directory '*' \
    # diretórios graváveis por qualquer UID
    && mkdir -p /app/output /home/app \
    && chmod 1777 /app/output /home/app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . .

ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/app \
    PYTHONDONTWRITEBYTECODE=1

# Default não-root; sobrescrito por --user em runtime
USER 1000:1000

ENTRYPOINT ["lkml-ground-truth"]