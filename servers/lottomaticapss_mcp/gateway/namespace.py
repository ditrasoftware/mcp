"""Stable direct-call names for tools exposed by remote MCP backends."""

from __future__ import annotations


class RemoteToolNamespace:
    """Build and parse remote:<remote_name>:<tool_name> addresses."""

    @staticmethod
    def make_full_name(remote_name: str, tool_name: str) -> str:
        return f"remote:{remote_name}:{tool_name}"

    @staticmethod
    def parse_full_name(full_name: str) -> tuple[str, str] | None:
        prefix, separator, remainder = full_name.partition(":")
        if prefix != "remote" or not separator:
            return None
        remote_name, separator, tool_name = remainder.partition(":")
        if not separator or not remote_name or not tool_name:
            return None
        return remote_name, tool_name