"""Standard error taxonomy template."""

from dataclasses import dataclass

# Standard error categories (used across all enterprise MCPs)
ERROR_CATEGORIES = [
    "VALIDATION_ERROR",
    "AUTH_ERROR",
    "AUTHZ_ERROR",
    "NOT_FOUND_ERROR",
    "CONFLICT_ERROR",
    "PROVIDER_ERROR",
    "TRANSIENT_ERROR",
    "RATE_LIMIT_ERROR",
    "TIMEOUT_ERROR",
    "INTERNAL_ERROR",
]


@dataclass
class ErrorInfo:
    """Structured error information."""
    
    category: str
    code: str
    message: str
    recoverable: bool = False
    details: dict | None = None


# TODO: Customize ERROR_TAXONOMY with your domain-specific errors
ERROR_TAXONOMY = {
    "VALIDATION_ERROR": ErrorInfo(
        category="VALIDATION_ERROR",
        code="VALIDATION_ERROR",
        message="Input validation failed",
        recoverable=False,
    ),
    "PROVIDER_ERROR": ErrorInfo(
        category="PROVIDER_ERROR",
        code="PROVIDER_ERROR",
        message="Downstream provider error",
        recoverable=False,
    ),
}
