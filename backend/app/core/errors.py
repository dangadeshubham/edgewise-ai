"""
EDGEWISE AI — Standardized Error Taxonomy & Exception Model

Defines system-wide error categories and typed exceptions that map cleanly
to safe HTTP responses, structured logs, and audit records without leaking
sensitive internals or stack traces.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ErrorCategory(str, Enum):
    """System-wide standardized error categories."""
    VALIDATION_ERROR = "VALIDATION_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    EDGE_ERROR = "EDGE_ERROR"
    OLLAMA_ERROR = "OLLAMA_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    REMOTE_ERROR = "REMOTE_ERROR"
    SYNC_ERROR = "SYNC_ERROR"
    CONFLICT_ERROR = "CONFLICT_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"


class EdgewiseException(Exception):
    """Base exception for all domain errors in EDGEWISE AI."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory,
        status_code: int = 500,
        retryable: bool = False,
        details: Optional[dict[str, Any]] = None,
        operation_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.operation_id = operation_id
        self.entity_id = entity_id
        self.entity_type = entity_type

    def to_dict(self) -> dict[str, Any]:
        """Produce safe client-facing error payload."""
        data: dict[str, Any] = {
            "error": self.category.value.lower(),
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.operation_id:
            data["operation_id"] = self.operation_id
        if self.details:
            data["details"] = self.details
        return data


class EdgewiseValidationError(EdgewiseException):
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.VALIDATION_ERROR,
            status_code=400,
            retryable=False,
            details=details,
            **kwargs,
        )


class EdgewiseStorageError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = False, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.STORAGE_ERROR,
            status_code=500,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseEmbeddingError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.EMBEDDING_ERROR,
            status_code=502,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseEdgeError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.EDGE_ERROR,
            status_code=503,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseOllamaError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.OLLAMA_ERROR,
            status_code=503,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseNetworkError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.NETWORK_ERROR,
            status_code=504,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseRemoteError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.REMOTE_ERROR,
            status_code=502,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseSyncError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.SYNC_ERROR,
            status_code=500,
            retryable=retryable,
            **kwargs,
        )


class EdgewiseConflictError(EdgewiseException):
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.CONFLICT_ERROR,
            status_code=409,
            retryable=False,
            **kwargs,
        )


class EdgewiseTimeoutError(EdgewiseException):
    def __init__(self, message: str, retryable: bool = True, **kwargs) -> None:
        super().__init__(
            message=message,
            category=ErrorCategory.TIMEOUT_ERROR,
            status_code=504,
            retryable=retryable,
            **kwargs,
        )
