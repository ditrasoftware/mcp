"""OAuth 2.1 + GCIP utilities - PKCE, DPoP, and token binding.

References:
- RFC 7636: Proof Key for Public Clients (PKCE)
- RFC 9126: OAuth 2.0 Proof Key for Public Clients (PKCE)
- RFC 9449: OAUTH 2.0 DEMONSTRATION OF PROOF-OF-POSSESSION (DPoP)
- RFC 9106: SCRAM: Salted Challenge Response Authentication Mechanism
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


def _b64url(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Base64url decode with automatic padding."""
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


# ============================================================================
# PKCE (RFC 7636 + RFC 9126) - Proof Key for Public Clients
# ============================================================================

@dataclass
class PKCEChallenge:
    """PKCE challenge for authorization request."""
    verifier: str  # 43-128 character random string
    challenge: str  # Base64url(SHA256(verifier)) for S256 method
    method: str = "S256"  # "S256" (recommended) or "plain"


def generate_pkce_challenge(method: str = "S256", length: int = 128) -> PKCEChallenge:
    """Generate PKCE challenge for authorization code flow.
    
    Args:
        method: "S256" (SHA256) or "plain" (not recommended)
        length: Verifier length, 43-128 characters (default 128)
    
    Returns:
        PKCEChallenge with verifier and challenge
    """
    if length < 43 or length > 128:
        raise ValueError("PKCE verifier length must be 43-128 characters")
    
    # Generate random verifier: unreserved characters per RFC 7636
    verifier = _b64url(secrets.token_bytes(int(length * 0.75))).rstrip("=")[:length]
    
    if method == "S256":
        challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    elif method == "plain":
        challenge = verifier
    else:
        raise ValueError(f"Unknown PKCE method: {method}")
    
    return PKCEChallenge(verifier=verifier, challenge=challenge, method=method)


def validate_pkce_response(
    verifier: str,
    challenge: str,
    method: str = "S256",
    enforce_s256: bool = True,
) -> bool:
    """Validate PKCE response (server-side verification).
    
    Args:
        verifier: Client's original verifier
        challenge: Server's stored challenge
        method: Challenge method ("S256" or "plain")
        enforce_s256: If True, reject "plain" method (OAuth 2.1 compliance)
    
    Returns:
        True if valid, False otherwise
    """
    if enforce_s256 and method != "S256":
        logger.warning(f"PKCE method {method} rejected (enforce_s256=True)")
        return False
    
    if method == "S256":
        expected = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
        return hmac.compare_digest(expected, challenge)
    elif method == "plain":
        return hmac.compare_digest(verifier, challenge)
    else:
        return False


# ============================================================================
# DPoP (RFC 9449) - Demonstration of Proof-of-Possession
# ============================================================================

@dataclass
class DoPProof:
    """DPoP proof for token binding."""
    header: dict[str, Any]  # JWT header (alg, typ, jwk)
    payload: dict[str, Any]  # JWT payload (jti, iat, exp, htm, htu, etc.)
    signature: str  # Base64url(Sign(header + payload))
    token: str  # Serialized DPoP proof JWT


class DoPProvider:
    """Generate and validate DPoP proofs (RFC 9449)."""
    
    def __init__(self, private_key: str | None = None, key_id: str | None = None):
        """Initialize DPoP provider.
        
        Args:
            private_key: Optional private key for signing proofs (ES256 or RS256)
            key_id: Optional key ID for proof header
        """
        self.private_key = private_key
        self.key_id = key_id
        self._nonce: str | None = None
        self._nonce_expires_at: float = 0.0
    
    def set_server_nonce(self, nonce: str, ttl_seconds: int = 60) -> None:
        """Update server's DPoP nonce (for nonce-challenge response).
        
        Args:
            nonce: Server's nonce
            ttl_seconds: Nonce validity period
        """
        self._nonce = nonce
        self._nonce_expires_at = time.time() + ttl_seconds
    
    def generate_proof(
        self,
        http_method: str,
        http_uri: str,
        token: str | None = None,
        access_token: str | None = None,
    ) -> DoPProof:
        """Generate DPoP proof for HTTP request.
        
        Args:
            http_method: HTTP method (GET, POST, etc.)
            http_uri: Request URI
            token: Optional token hash for resource request
            access_token: Optional access token to bind to
        
        Returns:
            DoPProof JWT
        """
        # Generate unique proof ID
        jti = _b64url(secrets.token_bytes(16))
        
        now = int(time.time())
        
        # DPoP proof payload
        payload = {
            "jti": jti,
            "htm": http_method.upper(),
            "htu": http_uri,
            "iat": now,
            "exp": now + 60,  # 60-second validity window
        }
        
        # Include server's nonce if valid
        if self._nonce and time.time() < self._nonce_expires_at:
            payload["nonce"] = self._nonce
        
        # Include access token hash if provided (binding to specific token)
        if access_token or token:
            token_to_hash = access_token or token or ""
            ath = _b64url(hashlib.sha256(token_to_hash.encode("utf-8")).digest())
            payload["ath"] = ath
        
        # DPoP header
        header = {
            "alg": "ES256",  # Recommend ES256 (ECDSA) over RS256
            "typ": "dpop+jwt",
            "jwk": self._jwk() if self.private_key else None,
        }
        
        if self.key_id:
            header["kid"] = self.key_id
        
        # Remove None values
        header = {k: v for k, v in header.items() if v is not None}
        
        # Sign proof (use stub signing for now; real implementation needs cryptography lib)
        # In production, use proper JWT signing with ES256 or RS256
        header_b64 = _b64url(json.dumps(header).encode("utf-8"))
        payload_b64 = _b64url(json.dumps(payload).encode("utf-8"))
        signature = self._sign(f"{header_b64}.{payload_b64}".encode("utf-8"))
        
        token_jwt = f"{header_b64}.{payload_b64}.{signature}"
        
        return DoPProof(header=header, payload=payload, signature=signature, token=token_jwt)
    
    def _jwk(self) -> dict[str, Any] | None:
        """Extract JWK from private key (stub - requires cryptography library)."""
        if not self.private_key:
            return None
        # In production, extract actual JWK from private key
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": "...",  # Base64url-encoded x-coordinate
            "y": "...",  # Base64url-encoded y-coordinate
        }
    
    def _sign(self, message: bytes) -> str:
        """Sign message with private key (stub implementation).
        
        In production, use cryptography library with ES256 or RS256.
        """
        if not self.private_key:
            # Fallback: HMAC signature with mock key
            sig = hmac.new(b"mock-key", message, hashlib.sha256).digest()
            return _b64url(sig)
        
        # In production:
        # from cryptography.hazmat.primitives import hashes
        # from cryptography.hazmat.primitives.asymmetric import ec
        # key = ec.derive_private_key(...)
        # signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
        
        return _b64url(hmac.new(self.private_key.encode("utf-8"), message, hashlib.sha256).digest())


# ============================================================================
# Token Binding (DPoP + Refresh Token Rotation)
# ============================================================================

@dataclass
class TokenBinding:
    """Token binding metadata for security context."""
    binding_method: str  # "dpop" | "tls_unique" | "mtls"
    binding_key: str  # DPoP proof JTI or certificate fingerprint
    bound_at: float  # Unix timestamp
    expires_at: float  # Binding validity end


class TokenBindingManager:
    """Manage token-to-proof binding for security."""
    
    def __init__(self, backend: str = "memory"):
        """Initialize binding manager.
        
        Args:
            backend: "memory" (process-local) or "redis" (distributed)
        """
        self.backend = backend
        self._bindings: dict[str, TokenBinding] = {}  # In-memory store
    
    def bind_token(
        self,
        access_token: str,
        binding_key: str,
        method: str = "dpop",
        ttl_seconds: int = 3600,
    ) -> TokenBinding:
        """Bind access token to proof (DPoP JTI or cert fingerprint).
        
        Args:
            access_token: Token to bind
            binding_key: DPoP proof JTI or certificate fingerprint
            method: Binding method
            ttl_seconds: Binding validity period
        
        Returns:
            TokenBinding metadata
        """
        now = time.time()
        binding = TokenBinding(
            binding_method=method,
            binding_key=binding_key,
            bound_at=now,
            expires_at=now + ttl_seconds,
        )
        
        # Store binding (would write to Redis in production)
        self._bindings[access_token] = binding
        
        logger.debug(f"Token bound to {method}: {binding_key}")
        return binding
    
    def verify_binding(
        self,
        access_token: str,
        binding_key: str,
        method: str = "dpop",
    ) -> bool:
        """Verify token-to-proof binding.
        
        Args:
            access_token: Token to verify
            binding_key: Proof JTI or certificate fingerprint
            method: Expected binding method
        
        Returns:
            True if binding is valid
        """
        binding = self._bindings.get(access_token)
        if not binding:
            return False
        
        # Check expiration
        if time.time() > binding.expires_at:
            self._bindings.pop(access_token, None)
            return False
        
        # Check binding matches
        if binding.binding_key != binding_key or binding.binding_method != method:
            logger.warning(f"Token binding mismatch: expected {binding.binding_key}, got {binding_key}")
            return False
        
        return True


# ============================================================================
# GCIP Integration Helpers
# ============================================================================

def extract_gcip_tenant_id(id_token_payload: dict[str, Any]) -> str | None:
    """Extract tenant ID from GCIP ID token.
    
    Looks for standard GCIP tenant claims:
    - organizations (array of org IDs)
    - org_id or organization_id
    - custom tenant claim
    
    Args:
        id_token_payload: Decoded ID token claims
    
    Returns:
        Tenant ID or None
    """
    # Try organizations array (primary GCIP claim)
    orgs = id_token_payload.get("organizations", [])
    if isinstance(orgs, list) and orgs:
        return str(orgs[0])  # Use first organization
    
    # Fallback to singular tenant claims
    for claim in ["org_id", "organization_id", "tenant_id", "account_id"]:
        value = id_token_payload.get(claim)
        if value:
            return str(value)
    
    return None


def extract_gcip_roles(id_token_payload: dict[str, Any]) -> list[str]:
    """Extract roles/groups from GCIP ID token.
    
    Looks for:
    - groups (array of group IDs)
    - roles (array of role names)
    
    Args:
        id_token_payload: Decoded ID token claims
    
    Returns:
        List of role identifiers
    """
    roles: list[str] = []
    
    # GCIP groups claim
    groups = id_token_payload.get("groups", [])
    if isinstance(groups, list):
        roles.extend(str(g) for g in groups)
    
    # Custom roles claim
    role_names = id_token_payload.get("roles", [])
    if isinstance(role_names, list):
        roles.extend(str(r) for r in role_names)
    
    return roles


def build_downstream_scope(base_scope: str, tenant_id: str | None) -> str:
    """Build scoped access for downstream MCP operations.
    
    Example:
        base_scope="tools:read", tenant_id="acme"
        -> "acme:tools:read"
    
    Args:
        base_scope: Base scope (e.g., "tools:read")
        tenant_id: Tenant ID or None
    
    Returns:
        Scoped scope string
    """
    if not tenant_id:
        return base_scope
    
    return f"{tenant_id}:{base_scope}"
