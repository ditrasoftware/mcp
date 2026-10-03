FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Reduce known CVEs in base OS packages
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Minimal runtime deps for Lottomaticapss MCP server
# IMPORTANT: Pin exact versions - prefab-ui has frequent breaking changes
# FastMCP 4.0.0+ required for response caching (cache_ttl, cache_scope)
# starlette/httpx versions are left to fastmcp's own dependency resolution
# to avoid conflicting with fastmcp-slim's starlette>=1.0.1 requirement.
RUN pip install --no-cache-dir \
    "fastmcp[apps]==4.0.3" \
    "prefab-ui==0.20.2" \
    "httpx==0.27.0"

# Copy only the MCP server package
COPY servers/lottomaticapss_mcp/ /app/lottomaticapss_mcp/

ENV PYTHONPATH=/app \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8001 \
    FASTMCP_STREAMABLE_HTTP_PATH=/mcp

EXPOSE 8001

CMD ["python", "-m", "lottomaticapss_mcp", "--transport", "http"]
