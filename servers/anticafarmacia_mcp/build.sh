#!/bin/bash
set -e

# Build DitraSoftware Template MCP Docker image
docker build -t anticafarmacia-mcp:latest .
