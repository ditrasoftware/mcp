from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .settings import DitraDevtestSettings


@dataclass(frozen=True)
class DitraDevtestAuth:
    access_token: str | None = None
    api_key: str | None = None
    refresh_token: str | None = None

    def as_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.access_token:
            token = self.access_token.strip()
            if token:
                if token.lower().startswith("bearer "):
                    headers["authorization"] = token
                else:
                    headers["authorization"] = f"Bearer {token}"
        if self.api_key:
            key = self.api_key.strip()
            if key:
                headers["x-api-key"] = key
        if self.refresh_token:
            rt = self.refresh_token.strip()
            if rt:
                headers["x-refresh-token"] = rt
        return headers

    def merged(self, other: DitraDevtestAuth) -> DitraDevtestAuth:
        return DitraDevtestAuth(
            access_token=other.access_token or self.access_token,
            api_key=other.api_key or self.api_key,
            refresh_token=other.refresh_token or self.refresh_token,
        )


class DitraDevtestRestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class DitraDevtestRestClient:
    def __init__(self, settings: DitraDevtestSettings):
        self._settings = settings

    @property
    def base_url(self) -> str:
        return self._settings.api_base_url

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        auth: DitraDevtestAuth | None = None,
        extra_headers: Mapping[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        if not self._settings.api_base_url:
            raise DitraDevtestRestError(
                "DitraDevtest REST backend is not configured: set DITRA_DEVTEST_API_BASE_URL"
            )
        url = f"{self._settings.api_base_url}{path}"
        headers: dict[str, str] = {}
        if extra_headers:
            headers.update({k.lower(): v for k, v in extra_headers.items() if v is not None})
        auth_headers: dict[str, str] = auth.as_headers() if auth else {}
        headers.update(auth_headers)

        timeout = httpx.Timeout(self._settings.timeout_seconds)
        async with httpx.AsyncClient(verify=self._settings.verify_ssl, timeout=timeout) as client:
            try:
                resp = await client.request(
                    method=method,
                    url=url,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    json=json,
                    headers=headers,
                )
            except httpx.RequestError as e:
                raise DitraDevtestRestError(f"REST request failed: {e}") from e

            if resp.status_code >= 400:
                try:
                    error_text = resp.text or f"HTTP {resp.status_code}"
                except Exception:
                    error_text = f"HTTP {resp.status_code}"
                raise DitraDevtestRestError(error_text, status_code=resp.status_code)

            if not expect_json:
                return resp.text

            try:
                return resp.json()
            except Exception as e:
                raise DitraDevtestRestError(
                    f"Failed to parse response as JSON: {e}",
                    status_code=resp.status_code,
                ) from e
