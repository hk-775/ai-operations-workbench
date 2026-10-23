FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
RUN apt-get update && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY workbench/ workbench/
COPY config/ config/
COPY data/ data/
COPY web/ web/
COPY scripts/healthcheck.py scripts/healthcheck.py
RUN useradd --create-home --uid 10001 workbench
USER 10001:10001
ENV PATH="/app/.venv/bin:$PATH" WORKBENCH_MODE=pilot
EXPOSE 8768
CMD ["uvicorn", "workbench.app:app", "--host", "0.0.0.0", "--port", "8768", "--no-proxy-headers", "--no-access-log"]
