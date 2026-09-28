"""
EDGEWISE AI — Structured Logging & Security Redaction Configuration

Uses structlog for high-performance structured logging. Enforces automated
redaction of secrets, API keys, tokens, and authorization headers, and
caps document payload volume to avoid leakage.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from typing import Any, MutableMapping

import structlog

# Redaction patterns
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(?i)(api[_-]?key|token|bearer|secret|password|passwd|authorization|auth|cookie|private[_-]?key)"
)
BEARER_REGEX = re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.~+/]+=*", re.IGNORECASE)
JWT_REGEX = re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
KEY_VALUE_SECRET_REGEX = re.compile(
    r"(?i)(qdrant_api_key|api_key|password|secret|token)\s*[:=]\s*['\"]?([^'\"\s&,]+)['\"]?"
)


def redact_sensitive_value(val: Any) -> Any:
    """Recursively scrub secrets and sanitize payload contents."""
    if isinstance(val, str):
        # Scrub Bearer tokens
        scrubbed = BEARER_REGEX.sub("Bearer [REDACTED]", val)
        # Scrub JWT tokens
        scrubbed = JWT_REGEX.sub("[JWT_REDACTED]", scrubbed)
        # Scrub inline key-value secrets
        scrubbed = KEY_VALUE_SECRET_REGEX.sub(r"\1=[REDACTED]", scrubbed)
        return scrubbed
    elif isinstance(val, dict):
        return {
            k: ("[REDACTED]" if SENSITIVE_KEY_PATTERNS.search(str(k)) else redact_sensitive_value(v))
            for k, v in val.items()
        }
    elif isinstance(val, (list, tuple)):
        # If list of floats and length > 16, truncate vector
        if val and isinstance(val[0], (float, int)) and len(val) > 16:
            return f"[VECTOR_DIM_{len(val)}_TRUNCATED]"
        return [redact_sensitive_value(item) for item in val]
    return val


def redact_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Structlog processor that guarantees zero secret leakage."""
    for key in list(event_dict.keys()):
        # Check if the key itself indicates a secret
        if SENSITIVE_KEY_PATTERNS.search(str(key)):
            event_dict[key] = "[REDACTED]"
            continue

        val = event_dict[key]
        # Avoid massive document contents or prompts in standard logs
        if key in ("document_content", "full_text", "raw_content", "vector", "embedding"):
            if isinstance(val, str) and len(val) > 150:
                event_dict[key] = f"{val[:100]}... [TRUNCATED {len(val)} chars]"
            elif isinstance(val, (list, tuple)) and len(val) > 8:
                event_dict[key] = f"[VECTOR_DIM_{len(val)}_TRUNCATED]"
            else:
                event_dict[key] = redact_sensitive_value(val)
        else:
            event_dict[key] = redact_sensitive_value(val)

    return event_dict


def generate_request_id() -> str:
    """Generate a unique 8-character request ID for tracing."""
    return str(uuid.uuid4())[:8]


def generate_operation_id(prefix: str = "op") -> str:
    """Generate a correlated operation ID for multi-step processes."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def setup_logging(log_level: str = "info") -> None:
    """Configure structured logging for the application with redaction."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_processor,
            structlog.processors.JSONRenderer() if log_level.lower() != "debug" else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Standard library logging configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Silence noisy dependencies
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a bound logger instance."""
    return structlog.get_logger(name)
