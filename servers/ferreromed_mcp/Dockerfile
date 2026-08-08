FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Reduce known CVEs in base OS packages
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Minimal runtime deps for FerreroMed MCP server
# IMPORTANT: Pin exact versions - prefab-ui has frequent breaking changes
# FastMCP 4.0.0+ required for response caching (cache_ttl, cache_scope)
RUN pip install --no-cache-dir \
    "fastmcp[apps]==4.0.0" \
    "prefab-ui==0.19.1" \
    "starlette==0.40.0" \
    "httpx==0.27.0"

# Copy only the MCP server package
COPY servers/ferreromed_mcp/ /app/ferreromed_mcp/

ENV PYTHONPATH=/app \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8001 \
    FASTMCP_STREAMABLE_HTTP_PATH=/mcp

EXPOSE 8001

CMD ["python", "-m", "ferreromed_mcp", "--transport", "http"]
