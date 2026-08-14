FROM python:3.13-slim

ARG FASTMCP_VERSION=4.0.0b2
ARG PREFAB_UI_VERSION=0.19.1

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Reduce known CVEs in base OS packages
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Minimal runtime deps for AnticaFarmacia MCP server.
# FastMCP 4.x is required for response caching and current server APIs.
RUN pip install --no-cache-dir \
    "fastmcp[apps]==${FASTMCP_VERSION}" \
    "prefab-ui==${PREFAB_UI_VERSION}" \
    "httpx==0.28.1"

# Copy only the MCP server package
COPY servers/anticafarmacia_mcp/ /app/anticafarmacia_mcp/

ENV PYTHONPATH=/app \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8001 \
    FASTMCP_STREAMABLE_HTTP_PATH=/mcp

EXPOSE 8001

CMD ["python", "-m", "anticafarmacia_mcp", "--transport", "http"]
