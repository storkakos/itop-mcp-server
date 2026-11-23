# iTop MCP server. Build and run with `docker compose up -d --build` (see compose.yaml).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Fixed non-root user; on Linux the host folder mounted at /data/logs must be writable by this UID.
RUN groupadd --system --gid 10001 mcp \
 && useradd --system --uid 10001 --gid mcp --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin mcp \
 && mkdir -p /data/logs \
 && chown mcp:mcp /data/logs

WORKDIR /app

# Pinned dependency tree first (cached layer), then the server itself without resolving again.
COPY requirements.lock ./
RUN pip install --no-deps -r requirements.lock
COPY pyproject.toml LICENSE-upstream-itop-mcp ./
COPY src ./src
RUN pip install --no-deps . \
 && pip check \
 && rm -rf /app/src

USER mcp
EXPOSE 8130
VOLUME ["/data/logs"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "itop_mcp_poc.healthcheck"]

CMD ["itop-mcp-server"]
