"""Client for the Ditra Analytics instance (Metabase Pro, self-hosted).

Wraps the Metabase REST API used by the `lottomatica-dashboard-webapp`
portal (site `https://analytics.ditra.io`, dashboard 30 "Lottomatica PSS
Dashboard", collection 6 "Lottomatica PSS Analytics"). Supports either
API-key auth (`X-API-KEY`, Metabase 47+) or session auth (`POST /api/session`
with username/password), matching what a self-hosted Pro instance offers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable, Mapping

import httpx

from .settings import MetabaseSettings


class MetabaseClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MetabaseResult:
    data: Any
    backend: str
    fallback_reason: str | None = None


class MetabaseClient:
    """MCP-first Ditra Analytics client with REST API augmentation."""

    def __init__(self, settings: MetabaseSettings):
        self._settings = settings
        self._session_token: str | None = None
        self._session_lock = asyncio.Lock()

    @property
    def settings(self) -> MetabaseSettings:
        return self._settings

    async def _auth_headers(self) -> dict[str, str]:
        if self._settings.api_key:
            return {"X-API-KEY": self._settings.api_key}
        token = await self._ensure_session_token()
        return {"X-Metabase-Session": token}

    async def _ensure_session_token(self) -> str:
        if self._session_token:
            return self._session_token
        async with self._session_lock:
            if self._session_token:
                return self._session_token
            if not self._settings.username or not self._settings.password:
                raise MetabaseClientError(
                    "Ditra Analytics credentials are not configured: set "
                    "METABASE_API_KEY, or METABASE_USERNAME/METABASE_PASSWORD"
                )
            payload = {"username": self._settings.username, "password": self._settings.password}
            data = await self._request("POST", "/api/session", json=payload, authed=False)
            token = data.get("id") if isinstance(data, dict) else None
            if not token:
                raise MetabaseClientError("Ditra Analytics login did not return a session token")
            self._session_token = token
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        authed: bool = True,
        _retry_on_401: bool = True,
    ) -> Any:
        if not self._settings.site_url:
            raise MetabaseClientError(
                "Ditra Analytics is not configured: set METABASE_SITE_URL"
            )
        url = f"{self._settings.site_url}{path}"
        headers: dict[str, str] = {}
        if authed:
            headers.update(await self._auth_headers())

        timeout = httpx.Timeout(self._settings.timeout_seconds)
        async with httpx.AsyncClient(verify=self._settings.verify_ssl, timeout=timeout) as http_client:
            try:
                resp = await http_client.request(
                    method,
                    url,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    json=json,
                    headers=headers,
                )
            except httpx.RequestError as e:
                raise MetabaseClientError(f"Ditra Analytics request failed: {e}") from e

        if resp.status_code == 401 and authed and _retry_on_401 and not self._settings.api_key:
            # Session token likely expired; clear and retry once.
            self._session_token = None
            return await self._request(
                method, path, params=params, json=json, authed=authed, _retry_on_401=False
            )

        if resp.status_code >= 400:
            try:
                detail = resp.text or f"HTTP {resp.status_code}"
            except Exception:
                detail = f"HTTP {resp.status_code}"
            raise MetabaseClientError(detail, status_code=resp.status_code)

        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception as e:
            raise MetabaseClientError(f"Failed to parse Ditra Analytics response: {e}") from e

    @staticmethod
    def _decode_mcp_response(response: httpx.Response, request_id: int) -> dict[str, Any]:
        payloads: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)

        payload = next((item for item in payloads if item.get("id") == request_id), None)
        if payload is None:
            raise MetabaseClientError("Ditra Analytics MCP returned no matching response")
        if payload.get("error"):
            error = payload["error"]
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise MetabaseClientError(f"Ditra Analytics MCP error: {detail}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise MetabaseClientError("Ditra Analytics MCP returned an invalid result")
        return result

    async def _mcp_call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self._settings.mcp_url:
            raise MetabaseClientError("Ditra Analytics MCP URL is not configured")

        headers = {
            **await self._auth_headers(),
            "Accept": "application/json, text/event-stream",
        }
        timeout = httpx.Timeout(self._settings.timeout_seconds)
        session_headers: dict[str, str] | None = None
        async with httpx.AsyncClient(
            verify=self._settings.verify_ssl,
            timeout=timeout,
        ) as http_client:
            try:
                initialize_id = 1
                response = await http_client.post(
                    self._settings.mcp_url,
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": initialize_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "lottomaticapss-mcp",
                                "version": "1.0",
                            },
                        },
                    },
                )
                response.raise_for_status()
                self._decode_mcp_response(response, initialize_id)
                session_id = response.headers.get("mcp-session-id")
                if not session_id:
                    raise MetabaseClientError(
                        "Ditra Analytics MCP did not establish a session"
                    )
                session_headers = {**headers, "Mcp-Session-Id": session_id}
                initialized = await http_client.post(
                    self._settings.mcp_url,
                    headers=session_headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )
                initialized.raise_for_status()

                call_id = 2
                response = await http_client.post(
                    self._settings.mcp_url,
                    headers=session_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": call_id,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    },
                )
                response.raise_for_status()
                result = self._decode_mcp_response(response, call_id)
                if result.get("isError"):
                    content = result.get("content") or []
                    detail = content[0].get("text") if content and isinstance(content[0], dict) else None
                    raise MetabaseClientError(detail or f"Ditra Analytics MCP tool {tool_name} failed")
                if "structuredContent" in result:
                    return result["structuredContent"]
                content = result.get("content") or []
                if content and isinstance(content[0], dict) and content[0].get("type") == "text":
                    text = content[0].get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text
                return result
            except httpx.HTTPStatusError as e:
                raise MetabaseClientError(
                    f"Ditra Analytics MCP returned HTTP {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            except httpx.RequestError as e:
                raise MetabaseClientError(f"Ditra Analytics MCP request failed: {e}") from e
            finally:
                if session_headers is not None:
                    try:
                        await http_client.delete(self._settings.mcp_url, headers=session_headers)
                    except httpx.RequestError:
                        pass

    async def _mcp_first(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        api_call: Callable[[], Awaitable[Any]],
    ) -> MetabaseResult:
        if self._settings.access_mode == "mcp_first":
            try:
                return MetabaseResult(await self._mcp_call(tool_name, arguments), "mcp")
            except MetabaseClientError as e:
                if not self._settings.api_fallback_enabled:
                    raise
                return MetabaseResult(await api_call(), "api", type(e).__name__)
        return MetabaseResult(await api_call(), "api")

    def normalize_page(self, limit: int | None, offset: int) -> tuple[int, int]:
        page_size = limit or self._settings.default_page_size
        if page_size <= 0 or page_size > self._settings.max_page_size:
            raise MetabaseClientError(
                f"limit must be between 1 and {self._settings.max_page_size}"
            )
        if offset < 0:
            raise MetabaseClientError("offset must be zero or greater")
        return page_size, offset

    # -- Read-only discovery -------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> MetabaseResult:
        page_size, offset = self.normalize_page(limit, offset)
        params: dict[str, Any] = {"q": query, "limit": page_size, "offset": offset}
        if models:
            params["models"] = models
        api_call = lambda: self._request("GET", "/api/search", params=params)
        if models or limit is not None or offset:
            return MetabaseResult(await api_call(), "api", "pagination_or_model_filter_requires_api")
        return await self._mcp_first(
            "search",
            {"term_queries": query, "semantic_queries": None},
            api_call,
        )

    async def api_search(
        self,
        query: str,
        *,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> MetabaseResult:
        page_size, offset = self.normalize_page(limit, offset)
        params: dict[str, Any] = {"q": query, "limit": page_size, "offset": offset}
        if models:
            params["models"] = models
        return MetabaseResult(
            await self._request("GET", "/api/search", params=params), "api"
        )

    async def get_dashboard(self, dashboard_id: int) -> MetabaseResult:
        return MetabaseResult(
            await self._request("GET", f"/api/dashboard/{dashboard_id}"),
            "api",
            "full_dashboard_layout_requires_api",
        )

    async def list_dashboard_cards(
        self,
        dashboard_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
        include_details: bool = False,
    ) -> MetabaseResult:
        page_size, offset = self.normalize_page(
            limit if limit is not None else self._settings.max_page_size,
            offset,
        )
        dashboard = await self._request("GET", f"/api/dashboard/{dashboard_id}")
        dashcards = dashboard.get("dashcards", []) if isinstance(dashboard, dict) else []
        compact: list[dict[str, Any]] = []
        for dashcard in dashcards[offset : offset + page_size]:
            card = dashcard.get("card") or {}
            visualization = dashcard.get("visualization_settings") or {}
            virtual_card = visualization.get("virtual_card") or {}
            item = {
                "type": "question" if card.get("id") else "virtual",
                "dashcard_id": dashcard.get("id"),
                "card_id": card.get("id") or dashcard.get("card_id"),
                "name": card.get("name") or virtual_card.get("name"),
                "display": card.get("display") or virtual_card.get("display"),
                "dashboard_tab_id": dashcard.get("dashboard_tab_id"),
                "row": dashcard.get("row"),
                "col": dashcard.get("col"),
                "size_x": dashcard.get("size_x"),
                "size_y": dashcard.get("size_y"),
            }
            if include_details:
                item["description"] = card.get("description")
                item["text"] = visualization.get("text")
                item["parameter_mappings"] = dashcard.get("parameter_mappings") or []
            compact.append(item)
        question_card_count = sum(
            bool((dashcard.get("card") or {}).get("id")) for dashcard in dashcards
        )
        return MetabaseResult(
            {
                "dashboard": {
                    "id": dashboard.get("id") if isinstance(dashboard, dict) else dashboard_id,
                    "name": dashboard.get("name") if isinstance(dashboard, dict) else None,
                },
                "data": compact,
                "total": len(dashcards),
                "question_card_count": question_card_count,
                "virtual_card_count": len(dashcards) - question_card_count,
                "limit": page_size,
                "offset": offset,
            },
            "api",
            "complete_dashboard_card_listing_requires_api",
        )

    async def get_card(self, card_id: int) -> MetabaseResult:
        async def api_call() -> Any:
            return await self._request("GET", f"/api/card/{card_id}")

        result = await self._mcp_first(
            "read_resource", {"uris": [f"metabase://question/{card_id}"]}, api_call
        )
        if result.backend != "mcp":
            return result
        resources = result.data.get("resources", []) if isinstance(result.data, dict) else []
        content = resources[0].get("content", {}) if resources else {}
        data = content.get("structured-output", content) if isinstance(content, dict) else content
        return MetabaseResult(data, result.backend, result.fallback_reason)

    async def api_get_card(self, card_id: int) -> MetabaseResult:
        return MetabaseResult(
            await self._request("GET", f"/api/card/{card_id}"), "api"
        )

    async def list_collection_items(
        self,
        collection_id: int,
        *,
        models: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> MetabaseResult:
        page_size, offset = self.normalize_page(limit, offset)
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        if models:
            params["models"] = models
        return MetabaseResult(
            await self._request(
                "GET", f"/api/collection/{collection_id}/items", params=params
            ),
            "api",
            "complete_collection_paging_requires_api",
        )

    # -- Query execution ------------------------------------------------------

    async def get_dashboard_card_data(
        self,
        dashboard_id: int,
        card_id: int,
        dashcard_id: int,
        *,
        parameters: list[dict[str, Any]] | None = None,
    ) -> MetabaseResult:
        return MetabaseResult(
            await self._request(
                "POST",
                f"/api/dashboard/{dashboard_id}/dashcard/{dashcard_id}/card/{card_id}/query",
                json={"parameters": parameters or []},
            ),
            "api",
            "dashboard_context_requires_api",
        )

    async def run_card_query(
        self, card_id: int, *, parameters: list[dict[str, Any]] | None = None
    ) -> MetabaseResult:
        api_call = lambda: self._request(
            "POST", f"/api/card/{card_id}/query", json={"parameters": parameters or []}
        )
        if parameters:
            return MetabaseResult(
                await api_call(), "api", "parameterized_question_requires_api"
            )
        return await self._mcp_first("execute_question", {"id": card_id}, api_call)

    async def api_run_card_query(
        self, card_id: int, *, parameters: list[dict[str, Any]] | None = None
    ) -> MetabaseResult:
        return MetabaseResult(
            await self._request(
                "POST", f"/api/card/{card_id}/query", json={"parameters": parameters or []}
            ),
            "api",
        )

    async def run_native_query(
        self,
        database_id: int,
        query: str,
        *,
        parameters: list[dict[str, Any]] | None = None,
        template_tags: dict[str, Any] | None = None,
    ) -> MetabaseResult:
        native: dict[str, Any] = {"query": query}
        if template_tags:
            native["template-tags"] = template_tags
        api_call = lambda: self._request(
            "POST", "/api/dataset", json={
                "type": "native",
                "native": native,
                "database": database_id,
                "parameters": parameters or [],
            },
        )
        if parameters or template_tags:
            return MetabaseResult(
                await api_call(), "api", "parameterized_sql_requires_api"
            )
        return await self._mcp_first(
            "execute_sql", {"database_id": database_id, "sql": query}, api_call
        )

    async def api_run_native_query(
        self,
        database_id: int,
        query: str,
        *,
        parameters: list[dict[str, Any]] | None = None,
        template_tags: dict[str, Any] | None = None,
    ) -> MetabaseResult:
        native: dict[str, Any] = {"query": query}
        if template_tags:
            native["template-tags"] = template_tags
        return MetabaseResult(
            await self._request(
                "POST",
                "/api/dataset",
                json={
                    "type": "native",
                    "native": native,
                    "database": database_id,
                    "parameters": parameters or [],
                },
            ),
            "api",
        )

    async def query(
        self,
        *,
        query: dict[str, Any] | None = None,
        query_handle: str | None = None,
        continuation_token: str | None = None,
    ) -> MetabaseResult:
        if self._settings.access_mode != "mcp_first":
            raise MetabaseClientError("Paged MCP queries require METABASE_ACCESS_MODE=mcp_first")
        data = await self._mcp_call(
            "query",
            {
                "query": query,
                "query_handle": query_handle,
                "continuation_token": continuation_token,
            },
        )
        return MetabaseResult(data, "mcp")
