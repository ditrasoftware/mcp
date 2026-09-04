from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from fnmatch import fnmatchcase
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
from authlib.jose import jwt
from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.auth import AuthenticationMiddleware, AuthContextMiddleware, RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from mcp.server.auth.middleware.bearer_auth import AuthCredentials, AuthenticatedUser
from starlette.authentication import AuthenticationBackend
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route


def _env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _list(name: str) -> list[str]:
    value = _env(name)
    return value.replace(",", " ").split() if value else []


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _pkce(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode()).digest())


class _ClientStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def write(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)


def _create_gcip_password_provider(base_url: str, resource_base_url: str | None) -> AuthProvider:
    api_key = _env("PLAYWRIGHT_MCP_GCIP_WEB_API_KEY")
    project_id = _env("PLAYWRIGHT_MCP_GCIP_PROJECT_ID")
    gcip_tenant = _env("PLAYWRIGHT_MCP_GCIP_TENANT_ID")
    application_tenant = _env("PLAYWRIGHT_MCP_APPLICATION_TENANT_ID") or gcip_tenant
    signing_secret = _env("PLAYWRIGHT_MCP_OAUTH_SIGNING_SECRET")
    redirects = _list("PLAYWRIGHT_MCP_OAUTH_ALLOWED_REDIRECT_URIS")
    if not all((api_key, project_id, gcip_tenant, signing_secret, redirects)):
        raise RuntimeError("GCIP auth requires web API key, project ID, tenant ID, signing secret, and redirect URIs")
    issuer = base_url.rstrip("/")
    scopes = _list("PLAYWRIGHT_MCP_OAUTH_REQUIRED_SCOPES")
    clients = _ClientStore(_env("PLAYWRIGHT_MCP_OAUTH_CLIENT_REGISTRATION_STORE_PATH") or "/var/lib/playwright-mcp/oauth-clients.json")
    used_codes: set[str] = set()
    gcip_verifier = JWTVerifier(jwks_uri="https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com", issuer=f"https://securetoken.google.com/{project_id}", audience=project_id)
    local_verifier = JWTVerifier(public_key=signing_secret, issuer=issuer, algorithm="HS256", audience="playwright-mcp", required_scopes=scopes)

    async def validate(params: dict[str, str]) -> Response | None:
        if params.get("response_type") != "code" or not params.get("client_id") or not params.get("redirect_uri"):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        client = clients.read().get(params["client_id"])
        if not client or params["redirect_uri"] not in client.get("redirect_uris", []):
            return JSONResponse({"error": "unauthorized_client"}, status_code=400)
        if not any(fnmatchcase(params["redirect_uri"], allowed) for allowed in redirects):
            return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
        if not params.get("code_challenge") or params.get("code_challenge_method") != "S256":
            return JSONResponse({"error": "invalid_request", "error_description": "PKCE S256 required"}, status_code=400)
        return None

    class GcipProvider(RemoteAuthProvider):
        def get_middleware(self) -> list:
            class BearerBackend(AuthenticationBackend):
                async def authenticate(self, conn: HTTPConnection):
                    header = conn.headers.get("authorization", "")
                    if not header.lower().startswith("bearer "):
                        return None
                    info = await local_verifier.verify_token(header[7:].strip())
                    if info:
                        return AuthCredentials(info.scopes), AuthenticatedUser(info)
                    return None
            return [Middleware(AuthenticationMiddleware, backend=BearerBackend()), Middleware(AuthContextMiddleware)]

        def get_routes(self, mcp_path: str | None = None) -> list[Route]:
            routes = super().get_routes(mcp_path)

            async def authorize_get(request: Request) -> Response:
                params = {key: str(request.query_params.get(key) or "") for key in ("response_type", "client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method")}
                error = await validate(params)
                if error:
                    return error
                hidden = "".join(f'<input type="hidden" name="{escape(key)}" value="{escape(value)}">' for key, value in params.items())
                return Response(f'<form method="post" action="/authorize">{hidden}<input name="email" type="email" required><input name="password" type="password" required><button>Sign in</button></form>', media_type="text/html", headers={"Cache-Control": "no-store"})

            async def authorize_post(request: Request) -> Response:
                form = await request.form()
                params = {key: str(form.get(key) or "") for key in ("response_type", "client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method")}
                error = await validate(params)
                if error:
                    return error
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword", params={"key": api_key}, json={"email": str(form.get("email") or ""), "password": str(form.get("password") or ""), "returnSecureToken": True, "tenantId": gcip_tenant})
                if response.status_code >= 400:
                    return JSONResponse({"error": "access_denied", "error_description": "Invalid email or password"}, status_code=401)
                identity = response.json()
                id_token = str(identity.get("idToken") or "")
                if not await gcip_verifier.verify_token(id_token):
                    return JSONResponse({"error": "access_denied"}, status_code=401)
                segment = id_token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
                if claims.get("firebase", {}).get("tenant") != gcip_tenant:
                    return JSONResponse({"error": "access_denied"}, status_code=401)
                now = int(time.time())
                payload = {"iss": issuer, "aud": "mcp-code", "iat": now, "exp": now + 180, "jti": secrets.token_urlsafe(16), "client_id": params["client_id"], "redirect_uri": params["redirect_uri"], "code_challenge": params["code_challenge"], "sub": claims.get("sub"), "email": claims.get("email"), "tenant_id": application_tenant}
                code = jwt.encode({"alg": "HS256"}, payload, signing_secret).decode()
                query = {"code": code}
                if params["state"]:
                    query["state"] = params["state"]
                separator = "&" if "?" in params["redirect_uri"] else "?"
                return RedirectResponse(f'{params["redirect_uri"]}{separator}{urlencode(query)}', status_code=302)

            async def token(request: Request) -> Response:
                form = parse_qs((await request.body()).decode(), keep_blank_values=True)
                try:
                    if form.get("grant_type", [""])[0] != "authorization_code":
                        raise ValueError
                    claims = jwt.decode(form.get("code", [""])[0], signing_secret)
                    if int(claims.get("exp", 0)) < int(time.time()) or claims["jti"] in used_codes:
                        raise ValueError
                    if _pkce(form.get("code_verifier", [""])[0]) != claims["code_challenge"]:
                        raise ValueError
                    used_codes.add(claims["jti"])
                except Exception:
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
                now = int(time.time())
                access = jwt.encode({"alg": "HS256"}, {"iss": issuer, "aud": "playwright-mcp", "iat": now, "exp": now + 3600, "sub": claims.get("sub"), "email": claims.get("email"), "tenant_id": application_tenant, "container_id": claims.get("client_id"), "scope": " ".join(scopes)}, signing_secret).decode()
                return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": 3600})

            async def register(request: Request) -> Response:
                body = await request.json()
                uris = body.get("redirect_uris")
                if not isinstance(uris, list) or not uris or any(not any(fnmatchcase(str(uri), allowed) for allowed in redirects) for uri in uris):
                    return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
                record = {"client_id": secrets.token_urlsafe(24), "redirect_uris": [str(uri) for uri in uris], "client_name": body.get("client_name"), "token_endpoint_auth_method": "none"}
                data = clients.read(); data[record["client_id"]] = record; clients.write(data)
                return JSONResponse(record, status_code=201)

            async def metadata(request: Request) -> Response:
                return JSONResponse({"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token", "registration_endpoint": f"{issuer}/register", "response_types_supported": ["code"], "grant_types_supported": ["authorization_code"], "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"]})

            async def protected_resource_metadata(request: Request) -> Response:
                resource = self._get_resource_url(mcp_path)
                return JSONResponse({"resource": str(resource or f"{issuer}/mcp"), "authorization_servers": [issuer], "scopes_supported": scopes, "bearer_methods_supported": ["header"], "resource_name": "Playwright MCP"})

            routes.extend([Route("/authorize", authorize_get, methods=["GET"]), Route("/authorize", authorize_post, methods=["POST"]), Route("/token", token, methods=["POST"]), Route("/register", register, methods=["POST"]), Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]), Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET", "OPTIONS"])])
            return routes

    return GcipProvider(token_verifier=local_verifier, authorization_servers=[issuer], base_url=base_url, scopes_supported=scopes, resource_base_url=resource_base_url, resource_name="Playwright MCP")


def create_auth_provider() -> AuthProvider | None:
    mode = (_env("PLAYWRIGHT_MCP_AUTH_MODE") or "off").lower()
    if mode in {"off", "none", "disabled", "false"}:
        return None
    base_url = _env("PLAYWRIGHT_MCP_BASE_URL")
    if not base_url:
        raise RuntimeError("PLAYWRIGHT_MCP_BASE_URL is required when authentication is enabled")
    if mode in {"gcip", "gcip_password", "gcip-password"}:
        return _create_gcip_password_provider(base_url, _env("PLAYWRIGHT_MCP_RESOURCE_BASE_URL"))
    raise RuntimeError("PLAYWRIGHT_MCP_AUTH_MODE must be off or gcip_password")
