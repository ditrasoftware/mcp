from __future__ import annotations

import os
import base64
import logging
import time
import hashlib
import hmac
import warnings
from urllib.parse import urlencode, parse_qs
from typing import Literal

from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.auth import RemoteAuthProvider
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.authentication import AuthenticationBackend
from starlette.requests import HTTPConnection
from starlette.requests import Request

warnings.filterwarnings(
    "ignore",
    message=r"authlib\.jose module is deprecated.*",
)

from authlib.jose import jwt
from fastmcp.server.auth.auth import AuthenticationMiddleware, AuthContextMiddleware

from mcp.server.auth.middleware.bearer_auth import (
    AccessToken,
    AuthCredentials,
    AuthenticatedUser,
)

logger = logging.getLogger(__name__)

try:
    # FastMCP depends on pydantic; keep optional for safety across environments.
    from pydantic import AnyHttpUrl  # type: ignore
except Exception:  # pragma: no cover
    AnyHttpUrl = str  # type: ignore[misc,assignment]


def _env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _basic_password(auth_header: str) -> str | None:
    raw = auth_header.strip()
    if not raw.lower().startswith("basic "):
        return None
    b64 = raw[6:].strip()
    if not b64:
        return None
    try:
        decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    _user, password = decoded.split(":", 1)
    password = password.strip()
    return password or None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _pkce_s256(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())


def _secure_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _env_list(name: str) -> list[str] | None:
    raw = _env(name)
    if raw is None:
        return None
    # allow comma or whitespace separated
    parts: list[str] = []
    for chunk in raw.replace(",", " ").split():
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts or None


def create_auth_provider() -> AuthProvider | None:
    """Create an optional FastMCP AuthProvider from environment.

    This enables standards-based OAuth/OIDC discovery endpoints on the MCP server
    so OAuth-capable clients can obtain and send Bearer tokens.

    Modes:
      - off (default): no OAuth/OIDC provider
      - oidc_proxy: FastMCP acts as a DCR-capable OAuth proxy to an upstream OIDC IdP
      - supabase: FastMCP verifies Supabase JWTs and forwards Supabase metadata

    Note:
      This only adds OAuth/OIDC support at the MCP HTTP layer. Your tools may still
      choose whether to require auth and how to forward credentials upstream.
    """

    mode = (_env("DITRA_DEVTEST_MCP_AUTH_MODE") or "off").lower()
    if mode in {"off", "0", "false", "none", "disabled"}:
        return None

    base_url = _env("DITRA_DEVTEST_MCP_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "DITRA_DEVTEST_MCP_AUTH_MODE is enabled but DITRA_DEVTEST_MCP_BASE_URL is not set "
            "(example: https://ferreromed.ditra.io)"
        )

    resource_base_url = _env("DITRA_DEVTEST_MCP_RESOURCE_BASE_URL")

    if mode in {"oidc_proxy", "oidc", "oidc-proxy"}:
        config_url = _env("DITRA_DEVTEST_OIDC_CONFIG_URL")
        client_id = _env("DITRA_DEVTEST_OIDC_CLIENT_ID")
        client_secret = _env("DITRA_DEVTEST_OIDC_CLIENT_SECRET")
        jwt_signing_key = _env("DITRA_DEVTEST_OIDC_JWT_SIGNING_KEY")

        if not config_url or not client_id:
            raise RuntimeError(
                "OIDC auth enabled but missing DITRA_DEVTEST_OIDC_CONFIG_URL and/or DITRA_DEVTEST_OIDC_CLIENT_ID"
            )
        if not client_secret and not jwt_signing_key:
            raise RuntimeError(
                "OIDC auth enabled but missing DITRA_DEVTEST_OIDC_CLIENT_SECRET (or set DITRA_DEVTEST_OIDC_JWT_SIGNING_KEY for public clients)"
            )

        required_scopes = _env_list("DITRA_DEVTEST_OIDC_REQUIRED_SCOPES")
        allowed_redirect_uris = _env_list("DITRA_DEVTEST_OIDC_ALLOWED_CLIENT_REDIRECT_URIS")
        verify_id_token = _env_bool("DITRA_DEVTEST_OIDC_VERIFY_ID_TOKEN", False)
        token_endpoint_auth_method = _env("DITRA_DEVTEST_OIDC_TOKEN_ENDPOINT_AUTH_METHOD")

        return OIDCProxy(
            config_url=config_url,
            client_id=client_id,
            client_secret=client_secret,
            jwt_signing_key=jwt_signing_key,
            base_url=base_url,
            resource_base_url=resource_base_url,
            required_scopes=required_scopes,
            allowed_client_redirect_uris=allowed_redirect_uris,
            verify_id_token=verify_id_token,
            token_endpoint_auth_method=token_endpoint_auth_method,
        )

    if mode in {"supabase"}:
        project_url = _env("SUPABASE_PROJECT_URL") or _env("SUPABASE_URL")
        if not project_url:
            raise RuntimeError(
                "Supabase auth enabled but missing SUPABASE_PROJECT_URL (or SUPABASE_URL)"
            )

        project_url = project_url.rstrip("/")

        # Supabase GoTrue is typically rooted at /auth/v1.
        auth_route = _env("SUPABASE_AUTH_ROUTE") or "/auth/v1"
        auth_route = "/" + auth_route.strip("/")

        # NOTE: Supabase GoTrue's /auth/v1/authorize is for *provider* login and is
        # not a generic OAuth authorization endpoint for arbitrary clients.
        # For Claude connectors (authorization_code + PKCE), we run a minimal local
        # OAuth AS on the MCP host at /authorize and /token.
        issuer_url = f"{project_url}{auth_route}"

        # Optional issuer override(s). Self-hosted Supabase/GoTrue deployments sometimes
        # emit `iss` values that differ from the project URL (e.g. different port, or a
        # configured external URL). If unset, HS256 verification will not enforce issuer.
        issuer_override = _env_list("SUPABASE_JWT_ISSUER")
        issuer: str | list[str] | None
        if issuer_override:
            issuer = issuer_override
        else:
            issuer = None

        # Prefer verifying with Supabase JWKS (RS256/ES256). If you're using HS256
        # tokens (shared JWT secret), set SUPABASE_JWT_SECRET and SUPABASE_JWT_ALGORITHM=HS256.
        jwt_secret = _env("SUPABASE_JWT_SECRET") or _env("JWT_SECRET")
        jwt_alg = (_env("SUPABASE_JWT_ALGORITHM") or "").upper() or None

        required_scopes = _env_list("DITRA_DEVTEST_SUPABASE_REQUIRED_SCOPES")

        # Token verification strategy:
        # - HS256 (self-hosted GoTrue commonly): use shared JWT secret
        # - Otherwise: verify via JWKS
        if jwt_alg == "HS256" and jwt_secret:
            token_verifier = JWTVerifier(
                public_key=jwt_secret,
                issuer=issuer,
                algorithm="HS256",
                audience="authenticated",
                required_scopes=required_scopes,
            )
        else:
            # Supabase commonly publishes JWKS at /auth/v1/.well-known/jwks.json
            jwks_uri = _env("SUPABASE_JWKS_URI") or f"{issuer_url}/.well-known/jwks.json"
            alg_override = (_env("SUPABASE_JWT_ASYMMETRIC_ALG") or "").upper() or None
            algorithm = alg_override if alg_override in {"RS256", "ES256"} else None

            # NOTE: We intentionally do NOT default issuer enforcement here because
            # some self-hosted setups emit non-URL `iss` values (e.g. "supabase-demo").
            token_verifier = JWTVerifier(
                jwks_uri=jwks_uri,
                issuer=issuer,
                algorithm=algorithm,
                audience="authenticated",
                required_scopes=required_scopes,
            )

        # Local OAuth issuer (this MCP host). This is what we advertise to clients.
        local_issuer = str(base_url).rstrip("/")
        authorization_server: AnyHttpUrl = AnyHttpUrl(local_issuer)  # type: ignore[call-arg]

        # Local OAuth settings
        oauth_signing_secret = (
            _env("DITRA_DEVTEST_OAUTH_SIGNING_SECRET")
            or _env("SUPABASE_JWT_SECRET")
            or _env("JWT_SECRET")
        )
        if not oauth_signing_secret:
            raise RuntimeError(
                "Supabase auth enabled but missing DITRA_DEVTEST_OAUTH_SIGNING_SECRET (or SUPABASE_JWT_SECRET/JWT_SECRET)"
            )

        oauth_shared_secret = _env("DITRA_DEVTEST_OAUTH_SHARED_SECRET")
        allowed_redirect_uris = _env_list("DITRA_DEVTEST_OAUTH_ALLOWED_REDIRECT_URIS") or [
            "https://claude.ai/api/mcp/auth_callback"
        ]
        allowed_client_ids = _env_list("DITRA_DEVTEST_OAUTH_ALLOWED_CLIENT_IDS")
        access_token_ttl_s = int(float(_env("DITRA_DEVTEST_OAUTH_ACCESS_TOKEN_TTL_SECONDS") or "3600"))
        code_ttl_s = int(float(_env("DITRA_DEVTEST_OAUTH_CODE_TTL_SECONDS") or "180"))

        # Verifier for locally-minted OAuth tokens (HS256) used by /authorize + /token.
        # Keep issuer strict for local tokens so random HS256 JWTs don't get accepted.
        local_token_verifier = JWTVerifier(
            public_key=oauth_signing_secret,
            issuer=local_issuer,
            algorithm="HS256",
            audience="authenticated",
            required_scopes=required_scopes,
        )

        class _StaticSupabaseAuthProvider(RemoteAuthProvider):
            def get_middleware(self) -> list:
                # Allow OAuth-capable clients to use Bearer JWTs, but also allow
                # Claude-style API key auth (Basic password or X-Api-Key) when enabled.
                allow_api_key = _env_bool("DITRA_DEVTEST_MCP_ALLOW_API_KEY_FALLBACK", True)

                token_verifier = self.token_verifier

                class _BearerOrApiKeyBackend(AuthenticationBackend):
                    async def authenticate(self, conn: HTTPConnection):
                        debug = _env_bool("DITRA_DEVTEST_MCP_AUTH_DEBUG", False)

                        # 1) Standard Bearer auth (OAuth)
                        auth_header = conn.headers.get("authorization")
                        if auth_header and auth_header.lower().startswith("bearer "):
                            token = auth_header[7:].strip()
                            if not token:
                                auth_header = None
                            else:
                                auth_info = await token_verifier.verify_token(token)
                                if not auth_info:
                                    # Try locally-minted tokens (Claude OAuth flow)
                                    auth_info = await local_token_verifier.verify_token(token)
                                if auth_info:
                                    return AuthCredentials(auth_info.scopes), AuthenticatedUser(auth_info)
                                if debug:
                                    logger.info(
                                        "Auth debug: Bearer presented but JWT verify failed (will try api-key/basic fallbacks=%s)",
                                        allow_api_key,
                                    )

                            if not allow_api_key:
                                return None

                        if not allow_api_key:
                            return None

                        # 2) X-Api-Key header
                        api_key = conn.headers.get("x-api-key")
                        if api_key and api_key.strip():
                            if debug:
                                logger.info("Auth debug: using X-Api-Key fallback")
                            info = AccessToken(
                                token=f"api_key:{api_key.strip()}",
                                client_id="api_key",
                                scopes=[],
                            )
                            return AuthCredentials([]), AuthenticatedUser(info)

                        # 3) Basic auth (Claude often sends API key as the password)
                        if auth_header and auth_header.lower().startswith("basic "):
                            pw = _basic_password(auth_header)
                            if pw:
                                if debug:
                                    logger.info("Auth debug: using Basic fallback (password)")
                                info = AccessToken(
                                    token=f"basic:{pw}",
                                    client_id="basic",
                                    scopes=[],
                                )
                                return AuthCredentials([]), AuthenticatedUser(info)

                        if debug:
                            scheme = None
                            if auth_header:
                                scheme = auth_header.strip().split(" ", 1)[0].lower()
                            logger.info(
                                "Auth debug: no usable auth (scheme=%s, has_x_api_key=%s)",
                                scheme,
                                bool(api_key and api_key.strip()),
                            )

                        return None

                return [
                    Middleware(AuthenticationMiddleware, backend=_BearerOrApiKeyBackend()),
                    Middleware(AuthContextMiddleware),
                ]

            def get_routes(self, mcp_path: str | None = None) -> list[Route]:
                routes = super().get_routes(mcp_path)

                async def oauth_authorize_local(request: Request):
                    # Minimal RFC6749 authorization endpoint (authorization_code + PKCE).
                    # This is designed for trusted desktop connectors.
                    qp = request.query_params
                    response_type = (qp.get("response_type") or "").strip()
                    client_id = (qp.get("client_id") or "").strip()
                    redirect_uri = (qp.get("redirect_uri") or "").strip()
                    state = (qp.get("state") or "").strip()
                    code_challenge = (qp.get("code_challenge") or "").strip()
                    code_challenge_method = (qp.get("code_challenge_method") or "").strip().upper()

                    if response_type.lower() != "code":
                        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
                    if not client_id or not redirect_uri:
                        return JSONResponse({"error": "invalid_request"}, status_code=400)
                    if allowed_client_ids and client_id not in allowed_client_ids:
                        return JSONResponse({"error": "unauthorized_client"}, status_code=400)
                    if redirect_uri not in allowed_redirect_uris:
                        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri not allowed"}, status_code=400)
                    if not code_challenge or code_challenge_method != "S256":
                        return JSONResponse({"error": "invalid_request", "error_description": "PKCE S256 required"}, status_code=400)

                    now = int(time.time())
                    code_claims = {
                        "iss": local_issuer,
                        "aud": "mcp_oauth_code",
                        "iat": now,
                        "exp": now + code_ttl_s,
                        "client_id": client_id,
                        "redirect_uri": redirect_uri,
                        "code_challenge": code_challenge,
                        "code_challenge_method": "S256",
                    }
                    code = jwt.encode(
                        {"alg": "HS256"},
                        code_claims,
                        oauth_signing_secret,
                    ).decode("utf-8")

                    params = {"code": code}
                    if state:
                        params["state"] = state
                    sep = "&" if ("?" in redirect_uri) else "?"
                    return RedirectResponse(url=f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)

                async def oauth_token_local(request: Request):
                    # Minimal RFC6749 token endpoint.
                    # Requires PKCE verifier and (optionally) a shared client secret.
                    body_bytes = await request.body()
                    form = parse_qs(body_bytes.decode("utf-8", errors="replace"), keep_blank_values=True)
                    grant_type = (form.get("grant_type", [""])[0] or "").strip()
                    code = (form.get("code", [""])[0] or "").strip()
                    redirect_uri = (form.get("redirect_uri", [""])[0] or "").strip()
                    client_id = (form.get("client_id", [""])[0] or "").strip()
                    code_verifier = (form.get("code_verifier", [""])[0] or "").strip()
                    client_secret = (form.get("client_secret", [""])[0] or "").strip()

                    # Also accept HTTP Basic for client credentials.
                    authz = request.headers.get("authorization")
                    if authz and authz.lower().startswith("basic "):
                        pw = _basic_password(authz)
                        if pw:
                            client_secret = client_secret or pw

                    debug = _env_bool("DITRA_DEVTEST_MCP_AUTH_DEBUG", False)

                    if grant_type != "authorization_code":
                        if debug:
                            logger.info("OAuth /token: unsupported grant_type=%r", grant_type)
                        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
                    if not code or not code_verifier:
                        if debug:
                            logger.info(
                                "OAuth /token: missing fields (has_code=%s has_code_verifier=%s)",
                                bool(code),
                                bool(code_verifier),
                            )
                        return JSONResponse({"error": "invalid_request"}, status_code=400)

                    if oauth_shared_secret:
                        if not client_secret or not _secure_eq(client_secret, oauth_shared_secret):
                            if debug:
                                logger.info(
                                    "OAuth /token: invalid_client (missing_or_wrong_client_secret=%s)",
                                    True,
                                )
                            return JSONResponse({"error": "invalid_client"}, status_code=401)

                    try:
                        claims = jwt.decode(code, oauth_signing_secret)
                    except Exception:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (code decode failed)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)

                    now = int(time.time())
                    exp = int(claims.get("exp") or 0)
                    if exp and exp < now:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (code expired)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)

                    expected_client_id = str(claims.get("client_id") or "")
                    expected_redirect_uri = str(claims.get("redirect_uri") or "")
                    expected_challenge = str(claims.get("code_challenge") or "")
                    if client_id and expected_client_id and client_id != expected_client_id:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (client_id mismatch)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)
                    if redirect_uri and expected_redirect_uri and redirect_uri != expected_redirect_uri:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (redirect_uri mismatch)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)
                    if not expected_challenge:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (missing code_challenge in code)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)

                    if _pkce_s256(code_verifier) != expected_challenge:
                        if debug:
                            logger.info("OAuth /token: invalid_grant (pkce mismatch)")
                        return JSONResponse({"error": "invalid_grant"}, status_code=400)

                    token_claims = {
                        "iss": local_issuer,
                        "aud": "authenticated",
                        "iat": now,
                        "exp": now + max(60, access_token_ttl_s),
                        "client_id": expected_client_id or (client_id or "claude"),
                        "sub": expected_client_id or (client_id or "claude"),
                        "scope": "",
                    }
                    access_token = jwt.encode(
                        {"alg": "HS256"},
                        token_claims,
                        oauth_signing_secret,
                    ).decode("utf-8")

                    return JSONResponse(
                        {
                            "access_token": access_token,
                            "token_type": "Bearer",
                            "expires_in": max(60, access_token_ttl_s),
                            "scope": "",
                        }
                    )

                async def oauth_authorization_server_metadata(_request):
                    if _request.method == "OPTIONS":
                        return JSONResponse({}, status_code=204)
                    # RFC 8414 (minimal, but sufficient for most OAuth clients).
                    metadata = {
                        "issuer": local_issuer,
                        "authorization_endpoint": f"{local_issuer}/authorize",
                        "token_endpoint": f"{local_issuer}/token",
                        "response_types_supported": ["code"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"],
                        "token_endpoint_auth_methods_supported": [
                            "client_secret_basic",
                            "client_secret_post",
                            "none",
                        ],
                    }
                    if required_scopes:
                        metadata["scopes_supported"] = required_scopes
                    return JSONResponse(metadata)

                # Some clients request the unscoped RFC9728 endpoint without the resource path.
                # FastMCP normally serves the *path-scoped* variant (e.g. /.../oauth-protected-resource/mcp).
                async def oauth_protected_resource_metadata_compat(_request):
                    if _request.method == "OPTIONS":
                        return JSONResponse({}, status_code=204)
                    # Mirror the path-scoped metadata that RemoteAuthProvider builds.
                    resource_url = self._get_resource_url(mcp_path)
                    if resource_url is None:
                        return JSONResponse({"error": "server_error", "error_description": "Missing resource URL"}, status_code=500)
                    payload = {
                        "resource": str(resource_url),
                        "authorization_servers": [local_issuer],
                    }
                    scopes = (
                        self._scopes_supported
                        if self._scopes_supported is not None
                        else self.token_verifier.scopes_supported
                    )
                    if scopes:
                        payload["scopes_supported"] = scopes
                    if self.resource_name:
                        payload["resource_name"] = self.resource_name
                    if self.resource_documentation:
                        payload["resource_documentation"] = str(self.resource_documentation)
                    return JSONResponse(payload)

                routes.append(
                    Route(
                        "/.well-known/oauth-authorization-server",
                        endpoint=oauth_authorization_server_metadata,
                        methods=["GET", "OPTIONS"],
                    )
                )
                routes.append(
                    Route(
                        "/.well-known/oauth-protected-resource",
                        endpoint=oauth_protected_resource_metadata_compat,
                        methods=["GET", "OPTIONS"],
                    )
                )

                # OAuth proxy endpoints for clients that incorrectly pin auth endpoints
                # to the resource host.
                routes.append(Route("/authorize", endpoint=oauth_authorize_local, methods=["GET"]))
                routes.append(Route("/token", endpoint=oauth_token_local, methods=["POST"]))

                return routes

        return _StaticSupabaseAuthProvider(
            token_verifier=token_verifier,
            authorization_servers=[authorization_server],
            base_url=base_url,
            scopes_supported=required_scopes,
            resource_base_url=resource_base_url,
            resource_name=_env("DITRA_DEVTEST_MCP_RESOURCE_NAME"),
            resource_documentation=(AnyHttpUrl(_env("DITRA_DEVTEST_MCP_RESOURCE_DOCUMENTATION")) if _env("DITRA_DEVTEST_MCP_RESOURCE_DOCUMENTATION") else None),  # type: ignore[call-arg]
        )

    raise RuntimeError(
        f"Unknown DITRA_DEVTEST_MCP_AUTH_MODE: {mode!r} (expected off|oidc_proxy|supabase)"
    )
