"""Standard error taxonomy for enterprise MCP.

All errors from tools/resources/prompts normalized to these categories.
"""

from __future__ import annotations

from dataclasses import dataclass

# Standard error categories
ERROR_CATEGORIES = [
    "VALIDATION_ERROR",    # Input validation failed
    "AUTH_ERROR",          # Auth missing or invalid
    "AUTHZ_ERROR",         # Permission denied (auth valid but not authorized)
    "NOT_FOUND_ERROR",     # Resource not found
    "CONFLICT_ERROR",      # Resource conflict (e.g., duplicate)
    "PROVIDER_ERROR",      # Downstream provider returned error
    "TRANSIENT_ERROR",     # Temporary failure (retriable)
    "RATE_LIMIT_ERROR",    # Rate limited
    "TIMEOUT_ERROR",       # Operation timed out
    "INTERNAL_ERROR",      # Server-side error
]


@dataclass
class ErrorInfo:
    """Structured error information."""
    
    category: str  # One of ERROR_CATEGORIES
    code: str  # Error code (e.g., "INVALID_DATE", "MISSING_SCOPE")
    message: str  # Human-readable message
    recoverable: bool = False  # Can be retried
    details: dict | None = None  # Extra context


ERROR_TAXONOMY = {
    # Validation errors
    "INVALID_DATE": ErrorInfo(
        category="VALIDATION_ERROR",
        code="INVALID_DATE",
        message="Date must be in YYYY-MM-DD format",
        recoverable=False,
    ),
    "MISSING_REQUIRED_FIELD": ErrorInfo(
        category="VALIDATION_ERROR",
        code="MISSING_REQUIRED_FIELD",
        message="Required field is missing",
        recoverable=False,
    ),
    
    # Auth errors
    "MISSING_AUTH": ErrorInfo(
        category="AUTH_ERROR",
        code="MISSING_AUTH",
        message="Authentication required",
        recoverable=False,
    ),
    "INVALID_TOKEN": ErrorInfo(
        category="AUTH_ERROR",
        code="INVALID_TOKEN",
        message="Auth token is invalid or expired",
        recoverable=True,
    ),
    "MISSING_SCOPE": ErrorInfo(
        category="AUTH_ERROR",
        code="MISSING_SCOPE",
        message="Auth token lacks required scope",
        recoverable=False,
    ),
    
    # Authz errors
    "PERMISSION_DENIED": ErrorInfo(
        category="AUTHZ_ERROR",
        code="PERMISSION_DENIED",
        message="Not authorized for this resource",
        recoverable=False,
    ),
    
    # Resource not found
    "NOT_FOUND": ErrorInfo(
        category="NOT_FOUND_ERROR",
        code="NOT_FOUND",
        message="Resource not found",
        recoverable=False,
    ),
    
    # Transient errors
    "PROVIDER_TIMEOUT": ErrorInfo(
        category="TRANSIENT_ERROR",
        code="PROVIDER_TIMEOUT",
        message="Downstream provider timed out",
        recoverable=True,
    ),
    "PROVIDER_UNAVAILABLE": ErrorInfo(
        category="TRANSIENT_ERROR",
        code="PROVIDER_UNAVAILABLE",
        message="Downstream provider is unavailable",
        recoverable=True,
    ),
    "RATE_LIMIT": ErrorInfo(
        category="RATE_LIMIT_ERROR",
        code="RATE_LIMIT",
        message="Rate limit exceeded",
        recoverable=True,
    ),
}
