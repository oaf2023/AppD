# MonedasAR Ledger Service - imagen multi-stage, non-root.
# Build: docker build -f services/ledger/Dockerfile -t platform/ledger:dev .
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/platform-kernel ./packages/platform-kernel
COPY packages/platform-contracts ./packages/platform-contracts
COPY services/ledger ./services/ledger

RUN uv sync --frozen --no-dev --no-editable --package ledger-service

FROM python:3.14-slim AS runtime

RUN useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# Migraciones Alembic fuera del paquete (se resuelven desde cwd; ver ledger/migrate.py)
COPY services/ledger/alembic.ini /app/alembic.ini
COPY services/ledger/migrations /app/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/healthz', timeout=2)"

CMD ["uvicorn", "ledger.main:app", "--host", "0.0.0.0", "--port", "8085"]
