"""
EDGEWISE AI — Conflict Constants and Error Types
"""

from enum import Enum


class ConflictState(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ConflictResolutionType(str, Enum):
    KEEP_LOCAL = "keep_local"
    KEEP_CLOUD = "keep_cloud"
    MERGE = "merge"
    MANUAL = "manual"


class ConflictAuditEvent(str, Enum):
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_OPENED = "conflict_opened"
    CONFLICT_CLAIMED = "conflict_claimed"
    CONFLICT_KEEP_LOCAL = "conflict_keep_local"
    CONFLICT_KEEP_CLOUD = "conflict_keep_cloud"
    CONFLICT_MERGED = "conflict_merged"
    CONFLICT_MANUAL = "conflict_manual"
    CONFLICT_DISMISSED = "conflict_dismissed"
    CONFLICT_RESOLVED = "conflict_resolved"


class ConflictError(Exception):
    """Base exception for conflict-related errors."""
    pass


class ConflictNotFoundError(ConflictError):
    """Raised when the requested conflict cannot be found."""
    pass


class ConflictStateError(ConflictError):
    """Raised when an invalid state transition is attempted on a conflict."""
    pass


class ConflictConcurrencyError(ConflictError):
    """Raised when optimistic locking detects concurrent modification."""
    pass


class ConflictValidationError(ConflictError):
    """Raised when resolution parameters or content fail validation."""
    pass
