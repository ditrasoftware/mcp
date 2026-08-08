from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .settings import FerreroMedSettings


@dataclass(frozen=True)
class FerreroMedAuth:
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

    def merged(self, other: FerreroMedAuth) -> FerreroMedAuth:
        return FerreroMedAuth(
            access_token=other.access_token or self.access_token,
            api_key=other.api_key or self.api_key,
            refresh_token=other.refresh_token or self.refresh_token,
        )


class FerreroMedRestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class FerreroMedRestClient:
    def __init__(self, settings: FerreroMedSettings):
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
        auth: FerreroMedAuth | None = None,
        extra_headers: Mapping[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        if not self._settings.api_base_url:
            raise FerreroMedRestError(
                "FerreroMed REST backend is not configured: set FERREROMED_API_BASE_URL (e.g. https://ferreromed.ditra.io)"
            )
        url = f"{self._settings.api_base_url}{path}"
        headers: dict[str, str] = {}
        if extra_headers:
            headers.update({k.lower(): v for k, v in extra_headers.items() if v is not None})
        auth_headers: dict[str, str] = auth.as_headers() if auth else {}
        headers.update(auth_headers)

        # If both Authorization and X-Api-Key are present, the underlying REST API
        # validates the Bearer token first and returns 401 on expired/invalid JWT,
        # never reaching the API key fallback. To make mixed-credential clients
        # more resilient, retry once with API-key-only on 401.
        has_bearer = bool(auth_headers.get("authorization"))
        has_api_key = bool(auth_headers.get("x-api-key"))
        allow_api_key_fallback = bool(auth and has_bearer and has_api_key)
        allow_refresh_retry = bool(
            auth
            and has_bearer
            and bool(auth_headers.get("x-refresh-token"))
            and path != "/auth/refresh"
        )

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
                raise FerreroMedRestError(f"REST request failed: {e}") from e

            # If the Bearer token is expired/invalid but we have a refresh token,
            # refresh once and retry the original request.
            if allow_refresh_retry and resp.status_code == 401:
                rt = auth_headers.get("x-refresh-token")
                if rt:
                    try:
                        refresh_resp = await client.request(
                            method="POST",
                            url=f"{self._settings.api_base_url}/auth/refresh",
                            json={"refresh_token": rt},
                            headers={"x-refresh-token": rt},
                        )
                    except httpx.RequestError as e:
                        raise FerreroMedRestError(f"REST request failed: {e}") from e

                    if refresh_resp.status_code < 400:
                        try:
                            refresh_data = refresh_resp.json()
                        except Exception:
                            refresh_data = None

                        if isinstance(refresh_data, dict):
                            new_access = refresh_data.get("access_token")
                            new_refresh = refresh_data.get("refresh_token")
                            if isinstance(new_access, str) and new_access.strip():
                                retry_headers = dict(headers)
                                retry_headers["authorization"] = f"Bearer {new_access.strip()}"
                                if isinstance(new_refresh, str) and new_refresh.strip():
                                    retry_headers["x-refresh-token"] = new_refresh.strip()
                                try:
                                    resp = await client.request(
                                        method=method,
                                        url=url,
                                        params={k: v for k, v in (params or {}).items() if v is not None},
                                        json=json,
                                        headers=retry_headers,
                                    )
                                except httpx.RequestError as e:
                                    raise FerreroMedRestError(f"REST request failed: {e}") from e

            if allow_api_key_fallback and resp.status_code == 401:
                # Retry once without Authorization header.
                retry_headers = dict(headers)
                retry_headers.pop("authorization", None)
                try:
                    resp = await client.request(
                        method=method,
                        url=url,
                        params={k: v for k, v in (params or {}).items() if v is not None},
                        json=json,
                        headers=retry_headers,
                    )
                except httpx.RequestError as e:
                    raise FerreroMedRestError(f"REST request failed: {e}") from e

        if resp.status_code >= 400:
            detail: str | None = None
            try:
                data = resp.json()
                if isinstance(data, dict):
                    detail = str(data.get("detail") or data.get("message") or data)
                else:
                    detail = str(data)
            except Exception:
                detail = resp.text

            msg = f"FerreroMed REST error {resp.status_code} for {method} {path}: {detail}".strip()
            raise FerreroMedRestError(msg, status_code=resp.status_code)

        if not expect_json:
            return resp.text

        content_type = (resp.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            return resp.json()
        # FastAPI may return empty body on 204
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text
