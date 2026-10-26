FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741 AS dependencies
RUN apk add --no-cache git ca-certificates
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM python:3.13-alpine@sha256:bf12ecc0bea3f171d55145dd02c78b5eeb09f30ee2ac9cc2b4c9e4e8f5e30741
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=dependencies /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY workbench/ workbench/
COPY config/ config/
COPY data/ data/
COPY web/ web/
COPY scripts/healthcheck.py scripts/healthcheck.py
RUN addgroup -g 10001 workbench && adduser -D -u 10001 -G workbench workbench \
    && /usr/local/bin/python -m pip uninstall --yes pip setuptools
USER 10001:10001
ENV PATH="/app/.venv/bin:$PATH" WORKBENCH_MODE=pilot
EXPOSE 8768
CMD ["uvicorn", "workbench.app:app", "--host", "0.0.0.0", "--port", "8768", "--no-proxy-headers", "--no-access-log"]
