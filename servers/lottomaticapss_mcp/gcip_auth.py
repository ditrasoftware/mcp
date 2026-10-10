from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from weakref import WeakValueDictionary
from urllib.parse import urlencode, urlsplit

import httpx
from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


class GCIPTokenVerifier(JWTVerifier):
    def __init__(self, project_id: str, tenant_id: str, subjects: tuple[str, ...] = (),
                 access_claim: str | None = None, allow_any_tenant_user: bool = False):
        policies = sum((bool(subjects), bool(access_claim), allow_any_tenant_user))
        if not project_id or not tenant_id or policies != 1:
            raise ValueError("GCIP authentication requires project, tenant and exactly one access policy")
        if access_claim and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", access_claim):
            raise ValueError("GCIP access claim must be a simple claim name")
        super().__init__(
            jwks_uri="https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
            issuer=f"https://securetoken.google.com/{project_id}",
            audience=project_id,
        )
        self.tenant_id = tenant_id
        self.subjects = subjects
        self.access_claim = access_claim
        self.allow_any_tenant_user = allow_any_tenant_user

    async def verify_token(self, token: str):
        verified = await super().verify_token(token)
        if verified is None:
            return None
        firebase = verified.claims.get("firebase")
        if not isinstance(firebase, dict) or firebase.get("tenant") != self.tenant_id:
            return None
        if not verified.subject:
            return None
        if self.subjects and verified.subject not in self.subjects:
            return None
        if self.access_claim and verified.claims.get(self.access_claim) is not True:
            return None
        return verified.model_copy(update={"scopes": ["mcp:access"]})


class GCIPOAuthBridge(OAuthProxy):
    def __init__(self, *, project_id: str, tenant_id: str, api_key: str, auth_domain: str,
                 client_id: str, signing_key: str, subjects: tuple[str, ...] = (),
                 access_claim: str | None = None, allow_any_tenant_user: bool = False, base_url: str,
                 allowed_client_redirect_uris: list[str], client_storage=None):
        origin = urlsplit(base_url)
        if origin.scheme != "https" or not origin.hostname or origin.query or origin.fragment:
            raise ValueError("GCIP OAuth requires a public HTTPS base URL")
        if not api_key or len(signing_key) < 32 or not allowed_client_redirect_uris:
            raise ValueError("GCIP OAuth requires web API key, stable signing key and approved client callbacks")
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", auth_domain) or not client_id:
            raise ValueError("GCIP OAuth requires a valid auth domain and client identifier")
        self.project_id = project_id
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.auth_domain = auth_domain
        self.bridge_client_id = client_id
        self.bridge_secret = signing_key
        self.bridge_base = base_url.rstrip("/")
        self.bridge_origin = f"{origin.scheme}://{origin.netloc}"
        self.bridge_verifier = GCIPTokenVerifier(project_id, tenant_id, subjects, access_claim,
                             allow_any_tenant_user)
        self._bridge_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        super().__init__(
            upstream_authorization_endpoint=f"{self.bridge_base}/gcip/login",
            upstream_token_endpoint=f"{self.bridge_base}/gcip/token",
            upstream_client_id=client_id,
            upstream_client_secret=signing_key,
            token_verifier=self.bridge_verifier,
            base_url=base_url,
            allowed_client_redirect_uris=allowed_client_redirect_uris,
            valid_scopes=["mcp:access"],
            jwt_signing_key=signing_key,
            token_endpoint_auth_method="client_secret_post",
            forward_resource=False,
            fastmcp_access_token_expiry_seconds=300,
            client_storage=client_storage,
        )
        self.required_scopes = ["mcp:access"]

    def _key(self, value: str) -> str:
        return "gcip:" + hashlib.sha256(value.encode()).hexdigest()

    async def _transaction(self, state: str):
        if not state:
            return None
        return await self._transaction_store.get(key=state)

    async def login_page(self, request: Request):
        state = request.query_params.get("state", "")
        transaction = await self._transaction(state)
        challenge = request.query_params.get("code_challenge", "")
        if (transaction is None or request.query_params.get("client_id") != self.bridge_client_id
                or request.query_params.get("redirect_uri") != f"{self.bridge_base}/auth/callback"
                or request.query_params.get("code_challenge_method") != "S256" or not challenge):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        expected = base64.urlsafe_b64encode(hashlib.sha256(
            (transaction.proxy_code_verifier or "").encode()).digest()).decode().rstrip("=")
        if not hmac.compare_digest(expected, challenge):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        binding = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        await self._client_storage.put(key=self._key(state), value={
            "binding": self._key(binding), "csrf": self._key(csrf), "challenge": challenge
        }, collection="gcip-login", ttl=300)
        nonce = secrets.token_urlsafe(24)
        config = {"apiKey": self.api_key, "authDomain": self.auth_domain, "projectId": self.project_id}
        values = json.dumps({"config": config, "tenant": self.tenant_id, "state": state,
                             "csrf": csrf, "complete": f"{self.bridge_base}/gcip/complete"}).replace("<", "\\u003c")
        html = GCIP_LOGIN_HTML.replace("__NONCE__", nonce).replace("__VALUES__", values)
        response = HTMLResponse(html, headers={
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}' https://www.gstatic.com; "
                f"style-src 'nonce-{nonce}'; connect-src 'self' https://identitytoolkit.googleapis.com "
                "https://securetoken.googleapis.com https://www.googleapis.com; "
                f"frame-src https://{self.auth_domain}; img-src https://www.gstatic.com; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
        })
        response.set_cookie("__Host-gcip-login", binding, max_age=300, secure=True,
                            httponly=True, samesite="lax", path="/")
        return response

    async def complete_login(self, request: Request):
        if request.headers.get("origin") != self.bridge_origin:
            return JSONResponse({"error": "invalid_request"}, status_code=403)
        if len(await request.body()) > 32768:
            return JSONResponse({"error": "invalid_request"}, status_code=413)
        try:
            data = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if not isinstance(data, dict):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        state = data.get("state")
        csrf = data.get("csrf")
        identity_token = data.get("id_token")
        refresh_token = data.get("refresh_token")
        if not all(isinstance(value, str) and value and len(value) <= 16384
                   for value in (state, csrf, identity_token, refresh_token)):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        binding = request.cookies.get("__Host-gcip-login", "")
        record = await self._client_storage.get(key=self._key(state), collection="gcip-login")
        if (not isinstance(record, dict) or await self._transaction(state) is None
                or not hmac.compare_digest(record["binding"], self._key(binding))
                or not hmac.compare_digest(record["csrf"], self._key(csrf))):
            return JSONResponse({"error": "invalid_request"}, status_code=403)
        verified = await self.bridge_verifier.verify_token(identity_token)
        if verified is None:
            return JSONResponse({"error": "access_denied"}, status_code=403)
        lock = self._bridge_locks.setdefault(self._key(state), asyncio.Lock())
        async with lock:
            record = await self._client_storage.get(key=self._key(state), collection="gcip-login")
            if not isinstance(record, dict):
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            await self._client_storage.delete(key=self._key(state), collection="gcip-login")
            code = secrets.token_urlsafe(32)
            await self._client_storage.put(key=self._key(code), collection="gcip-codes", ttl=60,
                value={"id_token": identity_token, "refresh_token": refresh_token,
                       "subject": verified.subject, "challenge": record["challenge"],
                       "expires": time.time() + 60})
        redirect = f"{self.bridge_base}/auth/callback?" + urlencode({"code": code, "state": state})
        response = JSONResponse({"redirect": redirect}, headers={"Cache-Control": "no-store"})
        browser_session = secrets.token_urlsafe(32)
        await self._client_storage.put(key=self._key(browser_session), collection="gcip-browser-identity", ttl=3600,
            value={"id_token": identity_token, "subject": verified.subject})
        response.set_cookie("__Host-master-identity", browser_session, max_age=3600,
                            secure=True, httponly=True, samesite="lax", path="/")
        response.delete_cookie("__Host-gcip-login", path="/", secure=True, httponly=True, samesite="lax")
        return response

    async def browser_identity(self, request: Request):
        session = request.cookies.get("__Host-master-identity", "")
        if not session:
            return None
        record = await self._client_storage.get(key=self._key(session), collection="gcip-browser-identity")
        if not isinstance(record, dict):
            return None
        identity = await self.bridge_verifier.verify_token(record.get("id_token", ""))
        if identity is None or identity.subject != record.get("subject"):
            return None
        return identity

    async def _refreshed_tokens(self, refresh_token: str):
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                response = await client.post("https://securetoken.googleapis.com/v1/token",
                    params={"key": self.api_key},
                    data={"grant_type": "refresh_token", "refresh_token": refresh_token})
            except httpx.RequestError:
                return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        identity_token = payload.get("id_token")
        if not isinstance(identity_token, str):
            return None
        verified = await self.bridge_verifier.verify_token(identity_token)
        if verified is None:
            return None
        return {"access_token": identity_token, "token_type": "Bearer",
                "refresh_token": payload.get("refresh_token") or refresh_token,
                "expires_in": max(1, int(verified.expires_at or time.time()) - int(time.time())),
                "scope": "mcp:access", "subject": verified.subject}

    async def token_exchange(self, request: Request):
        if len(await request.body()) > 32768:
            return JSONResponse({"error": "invalid_request"}, status_code=413)
        form = await request.form()
        client_id = str(form.get("client_id") or "")
        client_secret = str(form.get("client_secret") or "")
        if (not hmac.compare_digest(client_id, self.bridge_client_id)
                or not hmac.compare_digest(client_secret, self.bridge_secret)):
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if form.get("grant_type") == "authorization_code":
            code = str(form.get("code") or "")
            verifier = str(form.get("code_verifier") or "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            lock = self._bridge_locks.setdefault(self._key(code), asyncio.Lock())
            async with lock:
                record = await self._client_storage.get(key=self._key(code), collection="gcip-codes")
                if (not isinstance(record, dict) or record["expires"] <= time.time()
                        or form.get("redirect_uri") != f"{self.bridge_base}/auth/callback"
                        or not hmac.compare_digest(record["challenge"], challenge)):
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
                await self._client_storage.delete(key=self._key(code), collection="gcip-codes")
            payload = await self._refreshed_tokens(record["refresh_token"])
            if payload is not None and payload.pop("subject") != record["subject"]:
                payload = None
        elif form.get("grant_type") == "refresh_token":
            payload = await self._refreshed_tokens(str(form.get("refresh_token") or ""))
            if payload is not None:
                payload.pop("subject", None)
        else:
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        if payload is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    def get_routes(self, mcp_path=None):
        return [*super().get_routes(mcp_path),
                Route("/gcip/login", self.login_page, methods=["GET"]),
                Route("/gcip/complete", self.complete_login, methods=["POST"]),
                Route("/gcip/token", self.token_exchange, methods=["POST"])]


GCIP_LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lottomatica PSS MCP</title><style nonce="__NONCE__">
body{margin:0;background:#f4f6f7;color:#20282b;font-family:Verdana,sans-serif;letter-spacing:0}
main{max-width:360px;margin:64px auto;padding:24px}h1{font:24px Georgia,serif;margin:0 0 28px}
label{display:block;font-size:14px;margin:16px 0 6px}input,button{box-sizing:border-box;width:100%;height:44px;border:1px solid #adb9bd;border-radius:4px;padding:10px;font:14px Verdana,sans-serif}
button{cursor:pointer;margin-top:16px;background:#166858;color:white}button:disabled{opacity:.6;cursor:wait}
#google{background:white;color:#20282b}#google img{width:18px;height:18px;vertical-align:middle;margin-right:8px}
#status{min-height:42px;font-size:13px;line-height:1.5;color:#a12828}@media(max-width:440px){main{margin:24px auto;padding:20px}}
</style></head><body><main><h1>Lottomatica PSS MCP</h1>
<form id="login"><label for="email">Email</label><input id="email" type="email" autocomplete="username" required>
<label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required>
<button id="submit" type="submit">Sign in</button></form>
<button id="google" type="button"><img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="">Continue with Google</button>
<p id="status" role="status" aria-live="polite"></p></main>
<script type="module" nonce="__NONCE__">
import {initializeApp} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";
import {getAuth,signInWithEmailAndPassword,GoogleAuthProvider,signInWithPopup,signOut,setPersistence,inMemoryPersistence} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";
const values=__VALUES__;
const auth=getAuth(initializeApp(values.config));auth.tenantId=values.tenant;
const form=document.getElementById("login"),status=document.getElementById("status");
const buttons=[document.getElementById("submit"),document.getElementById("google")];
async function connect(signIn){
 buttons.forEach(button=>button.disabled=true);status.textContent="";
 try{
  await setPersistence(auth,inMemoryPersistence);
  const result=await signIn();document.getElementById("password").value="";
  const response=await fetch(values.complete,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({state:values.state,csrf:values.csrf,id_token:await result.user.getIdToken(),refresh_token:result.user.refreshToken})});
  if(!response.ok)throw new Error("denied");
  const resultData=await response.json();const target=new URL(resultData.redirect);
  if(target.origin!==window.location.origin)throw new Error("redirect");
  await signOut(auth);window.location.assign(target.href);
 }catch(error){await signOut(auth).catch(()=>{});status.textContent="Sign-in was not completed. Check your account and access assignment.";buttons.forEach(button=>button.disabled=false);}
}
form.addEventListener("submit",event=>{event.preventDefault();connect(()=>signInWithEmailAndPassword(auth,document.getElementById("email").value,document.getElementById("password").value));});
document.getElementById("google").addEventListener("click",()=>connect(()=>signInWithPopup(auth,new GoogleAuthProvider())));
</script></body></html>"""