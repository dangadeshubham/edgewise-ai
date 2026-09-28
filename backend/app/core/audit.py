"""
EDGEWISE AI — Canonical Audit Event Types & Observability Contracts

Defines all audit events emitted across state changes in EDGEWISE AI.
Events represent actual state transitions, not mere endpoint invocations.
"""

from __future__ import annotations

from enum import Enum


class AuditEventType(str, Enum):
    """Canonical event types for the immutable audit trail."""
    # Document Lifecycle
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
    DOCUMENT_FAILED = "DOCUMENT_FAILED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    DOCUMENT_REINDEXED = "DOCUMENT_REINDEXED"

    # Memory Operations
    MEMORY_CREATED = "MEMORY_CREATED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    MEMORY_DELETED = "MEMORY_DELETED"

    # Device Operations
    DEVICE_REGISTERED = "DEVICE_REGISTERED"
    DEVICE_UPDATED = "DEVICE_UPDATED"

    # Connectivity & Dependencies
    CONNECTIVITY_OFFLINE = "CONNECTIVITY_OFFLINE"
    CONNECTIVITY_ONLINE = "CONNECTIVITY_ONLINE"
    DEPENDENCY_DEGRADED = "DEPENDENCY_DEGRADED"
    DEPENDENCY_RECOVERED = "DEPENDENCY_RECOVERED"

    # Synchronization
    SYNC_STARTED = "SYNC_STARTED"
    SYNC_UPLOAD_SUCCESS = "SYNC_UPLOAD_SUCCESS"
    SYNC_UPLOAD_FAILED = "SYNC_UPLOAD_FAILED"
    SYNC_DELETE_SUCCESS = "SYNC_DELETE_SUCCESS"
    SYNC_SNAPSHOT_STARTED = "SYNC_SNAPSHOT_STARTED"
    SYNC_SNAPSHOT_COMPLETED = "SYNC_SNAPSHOT_COMPLETED"
    SYNC_COMPLETED = "SYNC_COMPLETED"

    # Conflicts
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    CONFLICT_CLAIMED = "CONFLICT_CLAIMED"
    CONFLICT_KEEP_LOCAL = "CONFLICT_KEEP_LOCAL"
    CONFLICT_KEEP_CLOUD = "CONFLICT_KEEP_CLOUD"
    CONFLICT_MERGED = "CONFLICT_MERGED"
    CONFLICT_MANUAL = "CONFLICT_MANUAL"
    CONFLICT_DISMISSED = "CONFLICT_DISMISSED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"


def normalize_event_type(event_type: str) -> str:
    """
    Normalizes event type string to uppercase canonical format while
    preserving compatibility with legacy lowercase formats.
    """
    if not event_type:
        return ""
    cleaned = event_type.strip()
    # Map known legacy lowercase names if needed
    legacy_map = {
        "document_uploaded": AuditEventType.DOCUMENT_UPLOADED.value,
        "processing_started": "DOCUMENT_PROCESSING_STARTED",
        "processing_completed": AuditEventType.DOCUMENT_PROCESSED.value,
        "processing_failed": AuditEventType.DOCUMENT_FAILED.value,
        "document_deleted": AuditEventType.DOCUMENT_DELETED.value,
        "document_reindexed": AuditEventType.DOCUMENT_REINDEXED.value,
        "memory_record_created": AuditEventType.MEMORY_CREATED.value,
        "memory_record_updated": AuditEventType.MEMORY_UPDATED.value,
        "memory_record_deleted": AuditEventType.MEMORY_DELETED.value,
        "device_registered": AuditEventType.DEVICE_REGISTERED.value,
        "device_updated": AuditEventType.DEVICE_UPDATED.value,
        "conflict_detected": AuditEventType.CONFLICT_DETECTED.value,
        "conflict_claimed": AuditEventType.CONFLICT_CLAIMED.value,
        "conflict_keep_local": AuditEventType.CONFLICT_KEEP_LOCAL.value,
        "conflict_keep_cloud": AuditEventType.CONFLICT_KEEP_CLOUD.value,
        "conflict_merged": AuditEventType.CONFLICT_MERGED.value,
        "conflict_manual": AuditEventType.CONFLICT_MANUAL.value,
        "conflict_dismissed": AuditEventType.CONFLICT_DISMISSED.value,
        "conflict_resolved": AuditEventType.CONFLICT_RESOLVED.value,
    }
    lower = cleaned.lower()
    if lower in legacy_map:
        return legacy_map[lower]
    return cleaned.upper()
