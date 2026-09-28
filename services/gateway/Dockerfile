# [PROJECT_NAME] Gateway Service — imagen multi-stage, non-root.
# Build: docker build -f services/gateway/Dockerfile -t platform/gateway:dev .
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_FROZEN=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/platform-kernel ./packages/platform-kernel
COPY packages/platform-contracts ./packages/platform-contracts
COPY services/gateway ./services/gateway

RUN uv sync --frozen --no-dev --no-editable --package gateway-service

FROM python:3.13-slim AS runtime

RUN useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import socket; s = socket.create_connection(('127.0.0.1', 8080), 2); s.close()"

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
