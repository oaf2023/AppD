# MonedasAR Market Data Service — imagen multi-stage, non-root.
# Build: docker build -f services/market-data/Dockerfile -t platform/market-data:dev .
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/platform-kernel ./packages/platform-kernel
COPY packages/platform-contracts ./packages/platform-contracts
COPY services/market-data ./services/market-data

RUN uv sync --frozen --no-dev --no-editable --package market-data-service

FROM python:3.14-slim AS runtime

RUN useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY services/market-data/alembic.ini /app/alembic.ini
COPY services/market-data/migrations /app/migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8084

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import socket; s = socket.create_connection(('127.0.0.1', 8084), 2); s.close()"

CMD ["uvicorn", "market_data.main:app", "--host", "0.0.0.0", "--port", "8084"]
