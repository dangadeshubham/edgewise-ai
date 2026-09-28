"""
EDGEWISE AI — Conflict Services Package
"""

from app.services.conflict.constants import (
    ConflictAuditEvent,
    ConflictConcurrencyError,
    ConflictError,
    ConflictNotFoundError,
    ConflictResolutionType,
    ConflictState,
    ConflictStateError,
    ConflictValidationError,
)
from app.services.conflict.diff import (
    ConflictDiffResult,
    DiffEngine,
    DiffLine,
    FieldDiff,
)
from app.services.conflict.service import ConflictService

__all__ = [
    "ConflictService",
    "DiffEngine",
    "ConflictDiffResult",
    "DiffLine",
    "FieldDiff",
    "ConflictState",
    "ConflictResolutionType",
    "ConflictAuditEvent",
    "ConflictError",
    "ConflictNotFoundError",
    "ConflictStateError",
    "ConflictConcurrencyError",
    "ConflictValidationError",
]
