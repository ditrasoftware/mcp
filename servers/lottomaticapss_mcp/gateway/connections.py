from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from typing import Literal

from fastmcp.server.dependencies import get_access_token, get_context, get_http_request
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.middleware import Middleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class ConnectionAuthorizationError(ToolError, PermissionError):
    pass

@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    tenant: str
    scopes: tuple[str, ...] = ()


class IntegrationConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    remote: str = Field(min_length=1)
    mode: Literal["delegated", "service"]
    tenant: str = Field(min_length=1)
    issuer: str = Field(min_length=1)
    subjects: tuple[str, ...]
    credential_ref: str = Field(min_length=1)
    tools: tuple[str, ...]
    resources: tuple[str, ...] = ()
    prompts: tuple[str, ...] = ()
    enabled: bool = True
    downstream_account_id: str | None = None
    required_scopes: tuple[str, ...] = ()
    oauth_scopes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_policy(self):
        if not self.subjects or any(not value or value == "*" for value in self.subjects):
            raise ValueError("Connections require explicit verified subject assignments")
        if self.mode == "delegated" and len(self.subjects) != 1:
            raise ValueError("Delegated connections must have exactly one owner")
        if not self.tools or any(not value or value == "*" for value in self.tools):
            raise ValueError("Connections require an explicit tool allowlist")
        return self

    def owned_by(self, principal: Principal) -> bool:
        return (self.enabled and self.tenant == principal.tenant
            and self.issuer == principal.issuer and principal.subject in self.subjects
            and set(self.required_scopes).issubset(principal.scopes))


_ACTIVE_CONNECTIONS: ContextVar[dict[str, IntegrationConnection]] = ContextVar("integration_connections", default={})
_SESSION_PARTITION: ContextVar[str] = ContextVar("integration_session_partition", default="legacy")


def separation_enabled() -> bool:
    return bool((os.getenv("LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON") or "").strip())


def current_connection(remote_name: str) -> IntegrationConnection | None:
    connection = _ACTIVE_CONNECTIONS.get().get(remote_name)
    if connection is None and separation_enabled():
        raise ConnectionAuthorizationError(f"Connection required for integration {remote_name}")
    return connection


def session_partition() -> str:
    return _SESSION_PARTITION.get()


def verified_principal() -> Principal:
    return principal_from_token(get_access_token())


def principal_from_token(token) -> Principal:
    if token is None:
        raise ConnectionAuthorizationError("Verified master identity required")
    claims = token.claims
    firebase = claims.get("firebase")
    tenant = firebase.get("tenant") if isinstance(firebase, dict) else None
    tenant = tenant or claims.get("tenant_id") or claims.get("tid")
    issuer = claims.get("iss")
    subject = token.subject or claims.get("sub")
    if not all(isinstance(value, str) and value for value in (issuer, subject, tenant)):
        raise ConnectionAuthorizationError("Verified issuer, subject and tenant claims are required")
    return Principal(issuer=issuer, subject=subject, tenant=tenant, scopes=tuple(token.scopes))


@contextmanager
def connection_scope(principal: Principal, connections: dict[str, IntegrationConnection], session_id: str = ""):
    for remote_name, connection in connections.items():
        if remote_name != connection.remote or not connection.owned_by(principal):
            raise ConnectionAuthorizationError("Connection ownership mismatch")
    partition = hashlib.sha256(json.dumps(
        [principal.issuer, principal.subject, principal.tenant, session_id,
         sorted((name, item.id, item.credential_ref, item.downstream_account_id)
            for name, item in connections.items())], separators=(",", ":")
    ).encode()).hexdigest()
    active = _ACTIVE_CONNECTIONS.set(connections)
    session = _SESSION_PARTITION.set(partition)
    try:
        yield
    finally:
        _SESSION_PARTITION.reset(session)
        _ACTIVE_CONNECTIONS.reset(active)


class ConnectionRegistry:
    def __init__(self, connections: list[IntegrationConnection], *, user_ditra_template: IntegrationConnection | None = None):
        if len({item.id for item in connections}) != len(connections):
            raise ValueError("Duplicate connection IDs")
        refs: dict[str, IntegrationConnection] = {}
        for item in connections:
            previous = refs.get(item.credential_ref)
            if previous and (previous.mode == "delegated" or item.mode == "delegated"
                             or previous.tenant != item.tenant or previous.remote != item.remote):
                raise ValueError("Credential references cannot cross delegated owners, tenants or integrations")
            refs[item.credential_ref] = item
        self.connections = connections
        self.user_ditra_template = user_ditra_template

    @classmethod
    def from_env(cls):
        raw = os.getenv("LOTTOMATICAPSS_GATEWAY_CONNECTIONS_JSON") or "[]"
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Connection configuration must be an array")
        connections = [IntegrationConnection.model_validate(item) for item in data]
        self_service = os.getenv("LOTTOMATICAPSS_GATEWAY_DITRA_SELF_SERVICE", "").lower() in {
            "1", "true", "yes", "y", "on"
        }
        if not self_service:
            return cls(connections)
        if (os.getenv("LOTTOMATICAPSS_MCP_AUTH_MODE", "").lower() != "gcip"
                or os.getenv("LOTTOMATICAPSS_GCIP_ACCESS_MODE", "subjects").lower() != "tenant"):
            raise ValueError("Ditra account self-service requires GCIP tenant access mode")
        project_id = os.getenv("LOTTOMATICAPSS_GCIP_PROJECT_ID", "").strip()
        tenant_id = os.getenv("LOTTOMATICAPSS_GCIP_TENANT_ID", "").strip()
        if not project_id or not tenant_id:
            raise ValueError("Ditra account self-service requires the configured GCIP project and tenant")
        issuer = f"https://securetoken.google.com/{project_id}"
        templates = [item for item in connections
                     if item.remote == "ditra-analytics" and item.mode == "delegated"]
        if len(templates) != 1:
            raise ValueError("Ditra account self-service requires exactly one delegated Ditra policy template")
        template = templates[0]
        if template.issuer != issuer or template.tenant != tenant_id:
            raise ValueError("Ditra policy template must match the configured GCIP issuer and tenant")
        return cls(connections, user_ditra_template=template)

    def assigned(self, principal: Principal) -> list[IntegrationConnection]:
        assigned = [item for item in self.connections if item.owned_by(principal)]
        template = self.user_ditra_template
        if (template is None or template.remote in {item.remote for item in assigned}
                or principal.issuer != template.issuer or principal.tenant != template.tenant):
            return assigned
        identity_key = hashlib.sha256(json.dumps(
            [principal.issuer, principal.tenant, principal.subject], separators=(",", ":")
        ).encode()).hexdigest()[:24]
        user_connection = IntegrationConnection.model_validate({
            **template.model_dump(),
            "id": f"ditra-user-{identity_key}",
            "tenant": principal.tenant,
            "issuer": principal.issuer,
            "subjects": (principal.subject,),
            "credential_ref": f"ditra-user-{identity_key}",
            "downstream_account_id": None,
        })
        return [*assigned, user_connection]

    def authorize(self, principal: Principal, remote: str, *, tool: str | None = None,
                  resource: str | None = None, prompt: str | None = None):
        candidates = [item for item in self.assigned(principal) if item.remote == remote
                      and (tool is None or tool in item.tools)
                      and (resource is None or resource in item.resources)
                      and (prompt is None or prompt in item.prompts)]
        if len(candidates) != 1:
            logger.warning(json.dumps({"event": "integration_authorization", "decision": "denied",
                                       "issuer": principal.issuer, "subject": principal.subject,
                                       "tenant": principal.tenant, "integration": remote,
                                       "operation": tool or resource or prompt}))
            raise ConnectionAuthorizationError("Connection required or operation not authorized; configure one explicit connection")
        logger.info(json.dumps({"event": "integration_authorization", "decision": "allowed",
                                "issuer": principal.issuer, "subject": principal.subject,
                                "tenant": principal.tenant, "integration": remote,
                                "connection": candidates[0].id, "mode": candidates[0].mode,
                                "operation": tool or resource or prompt}))
        return candidates[0]


class ConnectionPolicyMiddleware(Middleware):
    def __init__(self, remotes):
        self.remotes = remotes
        self.registry = ConnectionRegistry.from_env()

    def remote_for(self, name: str) -> tuple[str, str]:
        for remote in self.remotes:
            if name.startswith(remote.namespace + "_"):
                return remote.name, name.removeprefix(remote.namespace + "_")
        return "ditra-analytics", name

    def scope(self, principal, connections):
        try:
            request = get_http_request()
        except RuntimeError:
            try:
                session_id = get_context().session_id or ""
            except RuntimeError:
                session_id = ""
        else:
            token = get_access_token()
            session_id = request.headers.get("mcp-session-id") or f"client:{token.client_id if token else ''}"
        return connection_scope(principal, connections, session_id)

    async def on_call_tool(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        name = re.sub(r"^_?[0-9a-f]{12}_", "", context.message.name)
        if name in {"get_business_guidance", "list_integration_connections", "connect_integration"}:
            with self.scope(principal, {}):
                return await call_next(context)
        arguments = context.message.arguments or {}
        if name == "gateway_call_remote_tool":
            remote_name, tool_name = arguments.get("remote_name"), arguments.get("tool_name")
        elif name == "gateway_call_tool_namespaced":
            parts = str(arguments.get("full_name") or "").split(":", 2)
            if len(parts) != 3 or parts[0] != "remote":
                raise ConnectionAuthorizationError("Invalid integration invocation")
            _, remote_name, tool_name = parts
        elif name.startswith("gateway_") or name == "registry_summary":
            raise ConnectionAuthorizationError("Administrative gateway operations are unavailable in connection mode")
        else:
            remote_name, tool_name = self.remote_for(name)
        connection = self.registry.authorize(principal, remote_name, tool=tool_name)
        with self.scope(principal, {remote_name: connection}):
            return await call_next(context)

    async def on_read_resource(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        uri = str(context.message.uri)
        if uri.startswith("skill://lottomatica-pss/"):
            with self.scope(principal, {}):
                return await call_next(context)
        remote_name = "ditra-analytics"
        for remote in self.remotes:
            if f"://{remote.namespace}/" in uri:
                remote_name = remote.name
        connection = self.registry.authorize(principal, remote_name, resource=uri)
        with self.scope(principal, {remote_name: connection}):
            return await call_next(context)

    async def on_list_tools(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        assigned: dict[str, IntegrationConnection] = {}
        for item in self.registry.assigned(principal):
            if item.remote in assigned:
                raise ConnectionAuthorizationError("Ambiguous integration catalog connection")
            assigned[item.remote] = item
        with self.scope(principal, assigned):
            tools = await call_next(context)
        return [tool for tool in tools if tool.name in {"get_business_guidance", "list_integration_connections", "connect_integration"}
                or any(self.remote_for(tool.name) == (item.remote, name)
                       for item in assigned.values() for name in item.tools)]

    async def on_list_resources(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        assigned = {}
        for item in self.registry.assigned(principal):
            if item.remote in assigned:
                raise PermissionError("Ambiguous integration catalog connection")
            assigned[item.remote] = item
        with self.scope(principal, assigned):
            resources = await call_next(context)
        allowed = {uri for item in assigned.values() for uri in item.resources}
        return [resource for resource in resources
                if str(resource.uri) in allowed or str(resource.uri).startswith("skill://lottomatica-pss/")]

    async def on_get_prompt(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        name = context.message.name
        if name in {"getting_started", "explore_dashboard_workflow"}:
            with self.scope(principal, {}):
                return await call_next(context)
        remote_name, prompt_name = self.remote_for(name)
        connection = self.registry.authorize(principal, remote_name, prompt=prompt_name)
        with self.scope(principal, {remote_name: connection}):
            return await call_next(context)

    async def on_discover(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        assigned = {}
        for item in self.registry.assigned(principal):
            if item.remote in assigned:
                raise PermissionError("Ambiguous integration catalog connection")
            assigned[item.remote] = item
        with self.scope(principal, assigned):
            return await call_next(context)

    async def on_list_resource_templates(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        verified_principal()
        return []

    async def on_list_prompts(self, context, call_next):
        if not separation_enabled():
            return await call_next(context)
        principal = verified_principal()
        assigned = {item.remote: item for item in self.registry.assigned(principal)}
        with self.scope(principal, assigned):
            prompts = await call_next(context)
        allowed = {(item.remote, name) for item in assigned.values() for name in item.prompts}
        return [prompt for prompt in prompts
                if prompt.name in {"getting_started", "explore_dashboard_workflow"}
                or self.remote_for(prompt.name) in allowed]


def integration_status() -> dict:
    if not separation_enabled():
        return {"mode": "legacy_service", "connections": [],
                "notice": "Per-user connection authorization is not enabled"}
    from .remote_auth import _load_runtime_remote_secrets, _REFRESH_FAILURES

    registry = ConnectionRegistry.from_env()
    principal = verified_principal()
    stored = _load_runtime_remote_secrets()
    connections = []
    for item in registry.assigned(principal):
        credentials = stored.get(f"connection:{item.credential_ref}", {})
        configured = bool(credentials.get("REFRESH_TOKEN") or credentials.get("ACCESS_TOKEN")
                          or (item.mode == "service" and credentials.get("API_KEY")))
        prefix = f"{item.remote}|"
        blocked = any(key.startswith(prefix) and f"|connection:{item.credential_ref}|" in key
                      and failure[0] == float("inf") for key, failure in _REFRESH_FAILURES.items())
        state = "Reconnect Required" if blocked else "Configured" if configured else "Connection Required"
        entry = {"id": item.id, "integration": item.remote, "mode": item.mode, "state": state}
        if credentials.get("ACCOUNT_EMAIL"):
            entry["account_email"] = credentials["ACCOUNT_EMAIL"]
        if (state != "Configured" and item.mode == "delegated" and item.remote == "ditra-analytics"
                and (os.getenv("LOTTOMATICAPSS_MCP_AUTH_MODE") or "").lower() == "gcip"):
            entry["next_action"] = {"tool": "connect_integration", "arguments": {"connection_id": item.id}}
            entry["message"] = "Your Ditra Analytics account can be connected through the indicated operation."
        connections.append(entry)
    return {"mode": "separated", "connections": connections}