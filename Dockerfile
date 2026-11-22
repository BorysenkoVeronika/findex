# Multi-stage build; runtime only receives the application, dependencies and index.
FROM ghcr.io/astral-sh/uv:0.9 AS uv
FROM python:3.13-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY . .
RUN uv sync --no-dev --no-editable --no-cache
RUN .venv/bin/python -m findex index data/ --out index.bin --positions

FROM python:3.13-slim
WORKDIR /app
RUN useradd --system --uid 10001 findex
COPY --from=builder --chown=findex:findex /app /app
ENV PATH="/app/.venv/bin:$PATH" INDEX_PATH="/app/index.bin" PORT=8000 PYTHONUNBUFFERED=1
USER findex
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "findex.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
