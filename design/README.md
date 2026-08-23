# Federator Gateway Design Proposals

This folder contains architecture recommendations for running one main MCP as a federator over multiple downstream MCPs with different connection and authentication strategies.

## Documents

- [Question 1: Tool Surface Strategy](open-question-1-tool-surface/design.md)
- [Question 2: Failure Policy Defaults](open-question-2-failure-policy/design.md)
- [Question 3: Authentication Propagation Model](open-question-3-auth-propagation/design.md)
- [Federator Baseline Architecture](federator-baseline/design.md)
- [FastMCP-First Federator Blueprint](fastmcp-first-federator/design.md)

## Decision Summary

- Prefer a namespaced default tool surface, with an optional curated global alias layer.
- Use fail-open for read-only/discovery paths and fail-closed for state-changing operations.
- Use delegated service credentials by default, with optional user-token propagation for explicitly approved endpoints.

## Governance

- Treat each document as a living design record.
- Record accepted decisions as ADR-style updates in the relevant document.
- Link implementation PRs to the corresponding design document section.

## FastMCP Principle

- Prefer native FastMCP capabilities first (mount, middleware, tool/resource/prompt/app registration, custom routes, transport options, and client/proxy integration) before introducing custom orchestration layers.
