from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import secrets
import time
from weakref import WeakValueDictionary
from urllib.parse import urlencode, urlsplit

import httpx
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .connections import (
    ConnectionAuthorizationError, ConnectionRegistry, Principal, connection_scope,
    principal_from_token, verified_principal,
)
from .remote_auth import _get_remote_env, _load_runtime_remote_secrets, _REFRESH_FAILURES, set_runtime_remote_credentials_async


ANALYTICS_OAUTH_SCOPES = (
    "mb:full", "agent:resource:read", "agent:search", "agent:question:execute",
    "agent:query", "agent:query:construct", "agent:query:execute",
    "agent:viz:mcp-ui:query", "agent:viz:mcp-ui:drill-through",
)


class DitraAccountOAuth:
    def __init__(self, auth, remotes):
        self.auth = auth
        self.storage = auth._client_storage
        self.base = str(auth.base_url).rstrip("/")
        self.remotes = {item.name: item for item in remotes}
        self.locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def key(self, value):
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def normalize_account_email(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Ditra Analytics account email must be text")
        normalized = value.strip().casefold()
        if (not normalized or len(normalized) > 254 or normalized.count("@") != 1
                or any(character.isspace() for character in normalized)):
            raise ValueError("Enter a valid Ditra Analytics account email")
        return normalized

    def selected(self, principal, connection_id):
        choices = ConnectionRegistry.from_env().assigned(principal)
        choices = [item for item in choices if item.mode == "delegated" and item.remote == "ditra-analytics"
                   and (not connection_id or item.id == connection_id)]
        if len(choices) != 1:
            raise ConnectionAuthorizationError("No unambiguous Ditra Analytics account connection is available")
        return choices[0]

    async def browser_owner(self, request, record):
        token = await self.auth.browser_identity(request)
        if token is None:
            return None
        principal = principal_from_token(token)
        if [principal.issuer, principal.subject, principal.tenant] != record.get("owner"):
            return None
        return principal

    async def ticket(self, principal, connection_id=None, *, reconnect=False, account_email=None):
        connection = self.selected(principal, connection_id)
        target_email = self.normalize_account_email(account_email)
        if target_email and connection.downstream_account_id:
            raise ConnectionAuthorizationError("This Ditra Analytics connection is pinned by its administrator and cannot switch accounts")
        reconnect = reconnect or target_email is not None
        credentials = _load_runtime_remote_secrets().get(f"connection:{connection.credential_ref}", {})
        blocked = any(f"|connection:{connection.credential_ref}|" in key and failure[0] == float("inf")
                      for key, failure in _REFRESH_FAILURES.items())
        if (not reconnect and not blocked and (credentials.get("REFRESH_TOKEN") or credentials.get("ACCESS_TOKEN"))):
            return {"connection_id": connection.id, "integration": "Ditra Analytics", "state": "Configured",
                    "setup_required": False, "account_email": credentials.get("ACCOUNT_EMAIL"),
                    "message": "Your Ditra Analytics account is already configured. No new authorization request was created."}
        if connection.remote not in self.remotes:
            raise ConnectionAuthorizationError("Ditra Analytics integration is not configured")
        scopes = connection.oauth_scopes or ANALYTICS_OAUTH_SCOPES
        if "mb:full" not in scopes:
            raise ConnectionAuthorizationError("Ditra Analytics MCP and REST access requires explicit mb:full consent")
        ticket = secrets.token_urlsafe(32)
        await self.storage.put(key=self.key(ticket), collection="integration-tickets", ttl=300,
            value={"owner": [principal.issuer, principal.subject, principal.tenant],
                         "connection_id": connection.id, "scopes": list(scopes),
                         "target_account_email": target_email})
        return {"connection_id": connection.id, "integration": "Ditra Analytics",
                "setup_url": f"{self.base}/connections/start?" + urlencode({"ticket": ticket}),
                "expires_in": 300, "requested_scopes": list(scopes),
                "setup_required": True,
                 "target_account_email": target_email,
                "permission_summary": "mb:full permits the general analytics API as the selected account, including any write permissions that account possesses. Gateway tool policies apply separately.",
                 "message": (f"Open the link in the same browser used for master login and authorize {target_email}. "
                    "The callback checks the signed-in Ditra Analytics account before saving. If another account is already signed in, sign out of Ditra Analytics in this browser and retry.")
                    if target_email else
                    "Open the link in the same browser used for master login. Sign into the intended Ditra Analytics account and approve access. Refresh tool discovery after completion."}

    def error(self, text, status=400):
        return HTMLResponse(
            "<!doctype html><html lang='en'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Ditra Analytics connection</title><main style='max-width:560px;margin:48px auto;padding:20px;font-family:Verdana,sans-serif'>"
            "<h1 style='font-size:22px'>Ditra Analytics connection</h1><p>" + html.escape(text) + "</p></main></html>",
            status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    async def start(self, request):
        ticket = request.query_params.get("ticket", "")
        if not ticket or len(ticket) > 128:
            return self.error("Invalid or expired connection link.")
        lock = self.locks.setdefault(self.key(ticket), asyncio.Lock())
        async with lock:
            record = await self.storage.get(key=self.key(ticket), collection="integration-tickets")
            if not isinstance(record, dict):
                return self.error("Invalid or expired connection link.")
            principal = await self.browser_owner(request, record)
            if principal is None:
                return self.error("Reconnect the master MCP in this browser, then request a new connection link.", 403)
            try:
                connection = self.selected(principal, record["connection_id"])
            except ConnectionAuthorizationError:
                return self.error("Connection assignment is no longer authorized.", 403)
            if record.get("target_account_email") and connection.downstream_account_id:
                return self.error("This Ditra Analytics connection is pinned by its administrator and cannot switch accounts.", 403)
            remote = self.remotes[connection.remote]
            parsed = urlsplit(remote.url)
            if parsed.scheme != "https" or not parsed.hostname:
                return self.error("The analytics integration requires a trusted HTTPS endpoint.")
            origin = f"{parsed.scheme}://{parsed.netloc}"
            callback = f"{self.base}/connections/callback"
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            state = secrets.token_urlsafe(32)
            binding = secrets.token_urlsafe(32)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    metadata = await client.get(origin + "/.well-known/oauth-authorization-server")
                    metadata.raise_for_status()
                    published = metadata.json()
                    for name in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
                        endpoint = published.get(name, "")
                        if urlsplit(endpoint).scheme != "https" or urlsplit(endpoint).netloc != parsed.netloc:
                            raise ValueError("Unexpected OAuth endpoint")
                    issuer = published.get("issuer")
                    if not isinstance(issuer, str) or urlsplit(issuer).scheme != "https" or urlsplit(issuer).netloc != parsed.netloc:
                        raise ValueError("Unexpected OAuth issuer")
                    revocation_endpoint = published.get("revocation_endpoint")
                    if revocation_endpoint and (urlsplit(revocation_endpoint).scheme != "https"
                            or urlsplit(revocation_endpoint).netloc != parsed.netloc):
                        raise ValueError("Unexpected revocation endpoint")
                    if "mb:full" not in published.get("scopes_supported", []):
                        raise ValueError("Full API scope not advertised")
                    if "S256" not in published.get("code_challenge_methods_supported", []):
                        raise ValueError("PKCE unsupported")
                    registration = await client.post(published["registration_endpoint"], json={
                        "client_name": "Lottomatica PSS Ditra Analytics account connection",
                        "redirect_uris": [callback], "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"], "token_endpoint_auth_method": "client_secret_basic",
                        "scope": " ".join(record["scopes"]), "application_type": "web"})
                    registration.raise_for_status()
                    credentials = registration.json()
                if not credentials.get("client_id") or not credentials.get("client_secret"):
                    raise ValueError("Missing client credentials")
            except (httpx.HTTPError, ValueError, KeyError):
                return self.error("Ditra Analytics OAuth setup failed. No account connection was saved.", 502)
            await self.storage.delete(key=self.key(ticket), collection="integration-tickets")
            await self.storage.put(key=self.key(state), collection="integration-oauth", ttl=600,
                value={**record, "client_id": credentials["client_id"], "client_secret": credentials["client_secret"],
                       "verifier": verifier, "binding": self.key(binding), "origin": origin,
                       "issuer": issuer, "issuer_required": published.get("authorization_response_iss_parameter_supported") is True,
                       "revocation_endpoint": revocation_endpoint,
                       "token_endpoint": published["token_endpoint"], "expires": time.time() + 600})
            authorize = published["authorization_endpoint"] + "?" + urlencode({
                "response_type": "code", "client_id": credentials["client_id"], "redirect_uri": callback,
                "scope": " ".join(record["scopes"]), "state": state, "resource": remote.url,
                "code_challenge": challenge, "code_challenge_method": "S256"})
            if record.get("target_account_email"):
                authorize += "&" + urlencode({"login_hint": record["target_account_email"]})
            response = RedirectResponse(authorize, status_code=302, headers={
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            response.set_cookie("__Host-integration-oauth", binding, max_age=600,
                                secure=True, httponly=True, samesite="lax", path="/")
            return response

    async def callback(self, request):
        state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        if not state or not code or len(state) > 128 or len(code) > 4096 or request.query_params.get("error"):
            return self.error("Analytics authorization was not completed.")
        lock = self.locks.setdefault(self.key(state), asyncio.Lock())
        async with lock:
            record = await self.storage.get(key=self.key(state), collection="integration-oauth")
            if not isinstance(record, dict) or record["expires"] <= time.time():
                return self.error("Authorization expired. Request a new connection link.")
            returned_issuer = request.query_params.get("iss")
            if (record.get("issuer_required") and not returned_issuer) or (
                    returned_issuer is not None and returned_issuer != record.get("issuer")):
                return self.error("Analytics authorization issuer does not match.", 403)
            principal = await self.browser_owner(request, record)
            binding = request.cookies.get("__Host-integration-oauth", "")
            if principal is None or not hmac.compare_digest(self.key(binding), record["binding"]):
                return self.error("Connection browser or identity does not match.", 403)
            try:
                connection = self.selected(principal, record["connection_id"])
            except ConnectionAuthorizationError:
                return self.error("Connection assignment is no longer authorized.", 403)
            remote = self.remotes[connection.remote]
            target_email = record.get("target_account_email")
            if target_email and connection.downstream_account_id:
                return self.error("This Ditra Analytics connection is pinned to an administrator-selected account and cannot switch accounts.", 403)
            await self.storage.delete(key=self.key(state), collection="integration-oauth")
            tokens = {}
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(record["token_endpoint"],
                        auth=(record["client_id"], record["client_secret"]), data={
                            "grant_type": "authorization_code", "code": code,
                            "redirect_uri": f"{self.base}/connections/callback", "code_verifier": record["verifier"],
                            "resource": remote.url})
                    response.raise_for_status()
                    tokens = response.json()
                    if not tokens.get("access_token") or not tokens.get("refresh_token"):
                        raise ValueError("No renewable grant")
                    granted = str(tokens.get("scope") or " ".join(record["scopes"])).split()
                    if "mb:full" not in granted:
                        raise ValueError("Full API scope not granted")
                    headers = {"Authorization": "Bearer " + tokens["access_token"]}
                    account = await client.get(record["origin"] + "/api/user/current", headers=headers)
                    account.raise_for_status()
                    account_data = account.json()
                    account_id = account_data["id"]
                    if not isinstance(account_id, int) or account_id <= 0:
                        raise ValueError("Invalid account identity")
                    account_id = str(account_id)
                    account_email = self.normalize_account_email(account_data.get("email"))
                    if target_email and account_email != target_email:
                        raise ValueError("Signed-in Ditra Analytics account does not match the requested email")
                    with connection_scope(principal, {connection.remote: connection}):
                        previous_credentials = _load_runtime_remote_secrets().get(
                            f"connection:{connection.credential_ref}", {}).copy()
                        previous = _get_remote_env(remote, "ACCOUNT_ID")
                    expected = connection.downstream_account_id or previous
                    if expected and expected != account_id and not target_email:
                        raise ValueError("Account mismatch")
                    dashboard = await client.get(record["origin"] + "/api/dashboard/30", headers=headers)
                    dashboard.raise_for_status()
                    with connection_scope(principal, {connection.remote: connection}):
                        await set_runtime_remote_credentials_async(remote, {
                            "TOKEN_ENDPOINT": record["token_endpoint"], "REFRESH_TOKEN": tokens["refresh_token"],
                            "CLIENT_ID": record["client_id"], "CLIENT_SECRET": record["client_secret"],
                            "TOKEN_ENDPOINT_AUTH_METHOD": "client_secret_basic", "SCOPE": " ".join(granted),
                            "ACCOUNT_ID": account_id, "ACCOUNT_EMAIL": account_email or ""},
                            allow_account_change=bool(target_email))
                    old_refresh = previous_credentials.get("REFRESH_TOKEN")
                    old_client_id = previous_credentials.get("CLIENT_ID")
                    old_client_secret = previous_credentials.get("CLIENT_SECRET")
                    if (target_email and old_refresh and old_client_id and old_client_secret
                            and (old_client_id != record["client_id"] or previous != account_id)):
                        await self.revoke_failed_grant({
                            "client_id": old_client_id,
                            "client_secret": old_client_secret,
                            "revocation_endpoint": record.get("revocation_endpoint"),
                        }, {"refresh_token": old_refresh})
            except ValueError as exc:
                await self.revoke_failed_grant(record, tokens)
                message = ("The signed-in Ditra Analytics account did not match the requested email; "
                           "the existing connection was left unchanged. Sign into the requested account in this browser and retry."
                           if "does not match the requested email" in str(exc) else
                           "Your Ditra Analytics account, mb:full grant or Dashboard 30 access could not be verified. No connection was saved.")
                return self.error(message, 403)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                await self.revoke_failed_grant(record, tokens)
                return self.error("Your Ditra Analytics account, mb:full grant or Dashboard 30 access could not be verified. No connection was saved.", 403)
            response = self.error(f"Ditra Analytics account {account_email or account_id} is connected. Return to the AI client, refresh tool discovery and retry the request.", 200)
            response.delete_cookie("__Host-integration-oauth", path="/", secure=True, httponly=True, samesite="lax")
            return response

    async def revoke_failed_grant(self, record, tokens):
        if not isinstance(tokens, dict):
            return
        token = tokens.get("refresh_token") or tokens.get("access_token")
        endpoint = record.get("revocation_endpoint")
        if not token or not endpoint:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(endpoint, auth=(record["client_id"], record["client_secret"]),
                                  data={"token": token, "token_type_hint": "refresh_token" if tokens.get("refresh_token") else "access_token"})
        except httpx.HTTPError:
            pass


def register_ditra_account_oauth(mcp, auth, remotes):
    if not callable(getattr(auth, "browser_identity", None)):
        return
    manager = DitraAccountOAuth(auth, remotes)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False,
                          "idempotentHint": False, "openWorldHint": True})
    async def connect_integration(connection_id: str | None = None, reconnect: bool = False,
                                  account_email: str | None = None) -> dict:
        """Return Ditra account status or create an expiring OAuth setup link.

        Setup requests mb:full and listed MCP scopes. This can authorize all API operations
        permitted to the chosen analytics account. Browser consent is required.
        A configured connection returns status unless reconnect=true. To choose or switch
        Ditra accounts, pass account_email; the callback verifies the signed-in account before
        saving and leaves the current grant unchanged on mismatch.
        """
        return await manager.ticket(verified_principal(), connection_id, reconnect=reconnect,
                                   account_email=account_email)

    mcp.custom_route("/connections/start", methods=["GET"])(manager.start)
    mcp.custom_route("/connections/callback", methods=["GET"])(manager.callback)
    return manager