"""EDGEWISE AI — Synchronization State Machine & Constants (Phase 6)

Defines explicit states, operations, error categories, and transition invariants.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Set


class SyncState(str, Enum):
    """
    Allowed synchronization lifecycle states.

    PENDING    → Enqueued, waiting to be claimed by a worker.
    PROCESSING → Currently claimed and being processed by a worker.
    SYNCED     → Successfully processed (terminal).
    FAILED     → Failed after reaching max retries or permanent error.
    CONFLICT   → Conflict detected between local and remote state.
    CANCELLED  → Manually or automatically cancelled (terminal).
    """
    PENDING = "pending"
    PROCESSING = "processing"
    SYNCED = "synced"
    FAILED = "failed"
    CONFLICT = "conflict"
    CANCELLED = "cancelled"


class SyncOperation(str, Enum):
    """Allowed queue operation types."""
    UPSERT = "upsert"
    DELETE = "delete"


class SyncErrorCategory(str, Enum):
    """
    Categorized synchronization error types.
    Enables intelligent backoff, alerting, and failure policy decisions.
    """
    TRANSIENT_NETWORK_ERROR = "transient_network_error"
    REMOTE_UNAVAILABLE = "remote_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    VALIDATION_ERROR = "validation_error"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMANENT_FAILURE = "permanent_failure"
    CONFLICT = "conflict"


# Categories that should NEVER be retried as they cannot succeed without code/data change
NON_RETRYABLE_ERROR_CATEGORIES: Set[SyncErrorCategory] = {
    SyncErrorCategory.VALIDATION_ERROR,
    SyncErrorCategory.AUTHENTICATION_ERROR,
    SyncErrorCategory.PERMANENT_FAILURE,
}


def is_retryable_error(category: SyncErrorCategory | str) -> bool:
    """Return True if the error category qualifies for exponential backoff retry."""
    if isinstance(category, str):
        try:
            category = SyncErrorCategory(category)
        except ValueError:
            return False
    return category not in NON_RETRYABLE_ERROR_CATEGORIES


# Explicit state transition rules
VALID_TRANSITIONS: dict[SyncState, Set[SyncState]] = {
    SyncState.PENDING: {
        SyncState.PROCESSING,
        SyncState.CANCELLED,
    },
    SyncState.PROCESSING: {
        SyncState.SYNCED,
        SyncState.FAILED,
        SyncState.CONFLICT,
        SyncState.PENDING,  # Recovered on crash / worker release
    },
    SyncState.FAILED: {
        SyncState.PENDING,   # Re-queued on retry or manual retry
        SyncState.CANCELLED,
    },
    SyncState.CONFLICT: {
        SyncState.PENDING,   # Re-queued after conflict resolution
        SyncState.CANCELLED,
    },
    SyncState.SYNCED: set(),      # Terminal state
    SyncState.CANCELLED: set(),   # Terminal state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted on a sync item."""

    def __init__(
        self,
        current_state: SyncState | str,
        target_state: SyncState | str,
        item_id: Optional[str] = None,
    ) -> None:
        self.current_state = current_state
        self.target_state = target_state
        self.item_id = item_id
        msg = f"Invalid sync state transition: '{current_state}' → '{target_state}'"
        if item_id:
            msg += f" for item '{item_id}'"
        super().__init__(msg)


def validate_transition(
    current: SyncState | str,
    target: SyncState | str,
    item_id: Optional[str] = None,
) -> None:
    """
    Validate that transitioning from `current` to `target` is allowed.
    Raises InvalidStateTransitionError if transition is illegal.
    """
    if isinstance(current, str):
        current = SyncState(current.lower())
    if isinstance(target, str):
        target = SyncState(target.lower())

    if current == target:
        return  # No-op transition is allowed

    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(current, target, item_id)
