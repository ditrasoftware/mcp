FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

ARG FASTMCP_VERSION=4.0.0b2
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
WORKDIR /app

RUN pip install --no-cache-dir "fastmcp==${FASTMCP_VERSION}" "google-cloud-storage==2.19.0" "httpx==0.28.1" "playwright==1.52.0"
COPY servers/playwright_mcp/ /app/playwright_mcp/

ENV FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8001 \
    FASTMCP_STREAMABLE_HTTP_PATH=/mcp
EXPOSE 8001
CMD ["python", "-m", "playwright_mcp", "--transport", "http"]
