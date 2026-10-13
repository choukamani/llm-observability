# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra demo --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra demo --no-editable

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY examples ./examples
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/examples PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "demo_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
