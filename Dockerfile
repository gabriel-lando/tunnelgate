# syntax=docker/dockerfile:1
# Base images use a fixed minor version; patch updates arrive through the monthly rebuild.
ARG PYTHON_IMAGE=python:3.15-slim
ARG NODE_IMAGE=node:24-slim

FROM ${NODE_IMAGE} AS frontend
ENV CI=true COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && corepack install && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM ${PYTHON_IMAGE} AS backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/build/uv-requirements.txt /tmp/uv-requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/uv-requirements.txt
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=dev
ARG COMMIT=unknown
LABEL org.opencontainers.image.title="Tunnelgate" \
      org.opencontainers.image.description="Kill switch and route manager for Cloudflare Tunnels" \
      org.opencontainers.image.source="https://github.com/gabriel-lando/tunnelgate" \
      org.opencontainers.image.url="https://hub.docker.com/r/gabriellando/tunnelgate" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${COMMIT}"
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TUNNELGATE_STATIC_DIR=/app/static \
    TUNNELGATE_DATA_DIR=/data \
    TUNNELGATE_VERSION=${VERSION} \
    TUNNELGATE_COMMIT=${COMMIT}
# pip is unused at runtime and ships vendored libraries that scanners flag.
RUN python -m pip uninstall --yes --no-cache-dir pip \
 && groupadd --system --gid 10001 tunnelgate \
 && useradd --system --uid 10001 --gid tunnelgate --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin tunnelgate \
 && mkdir -p /data \
 && chown tunnelgate:tunnelgate /data \
 && chmod 0700 /data
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /src/frontend/build /app/static
USER 10001:10001
WORKDIR /app
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
ENTRYPOINT ["tunnelgate"]
CMD ["serve"]
