# [PROJECT_NAME] Identity Service — imagen multi-stage, non-root.
# Build: docker build -f services/identity/Dockerfile -t platform/identity:dev .
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/platform-kernel ./packages/platform-kernel
COPY packages/platform-contracts ./packages/platform-contracts
COPY services/identity ./services/identity

RUN uv sync --frozen --no-dev --no-editable --package identity-service

FROM python:3.13-slim AS runtime

RUN useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# Migraciones Alembic fuera del paquete (se resuelven desde cwd; ver identity/migrate.py)
COPY services/identity/alembic.ini /app/alembic.ini
COPY services/identity/migrations /app/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=2)"

CMD ["uvicorn", "identity.main:app", "--host", "0.0.0.0", "--port", "8081"]
