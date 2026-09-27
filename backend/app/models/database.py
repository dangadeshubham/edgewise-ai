"""
EDGEWISE AI — SQLAlchemy Database Models

Complete relational schema for:
- Documents and versioning
- Document chunks
- Memory records
- Sync queue and attempts
- Conflicts
- Devices
- Sources
- Audit events
- Conversations
- Embedding metadata
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


# =============================================================================
# Device
# =============================================================================

class Device(Base):
    __tablename__ = "devices"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    site = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    software_version = Column(String(64), nullable=True)
    last_seen = Column(DateTime, default=utcnow, onupdate=utcnow)
    last_sync = Column(DateTime, nullable=True)
    pending_changes = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    documents = relationship("Document", back_populates="device")
    audit_events = relationship("AuditEvent", back_populates="device")


# =============================================================================
# Source
# =============================================================================

class Source(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    source_type = Column(String(64), nullable=False)  # manual, incident, maintenance, note, equipment
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    documents = relationship("Document", back_populates="source")


# =============================================================================
# Document
# =============================================================================

class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(64), ForeignKey("devices.id"), nullable=False)
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=True)

    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    mime_type = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)
    content_hash = Column(String(128), nullable=False)
    file_path = Column(String(1024), nullable=False)

    title = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    document_type = Column(String(64), nullable=True)  # manual, incident, maintenance, note, equipment

    processing_status = Column(
        String(32), nullable=False, default="pending"
    )
    processing_error = Column(Text, nullable=True)

    sensitivity = Column(String(32), nullable=False, default="internal")
    sync_status = Column(String(32), nullable=False, default="pending")

    version = Column(Integer, nullable=False, default=1)
    revision = Column(Integer, nullable=False, default=1)
    origin_device = Column(String(64), nullable=True)
    last_synced_revision = Column(Integer, nullable=True)

    chunk_count = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_documents_content_hash", "content_hash"),
        Index("ix_documents_device_id", "device_id"),
        Index("ix_documents_sync_status", "sync_status"),
        Index("ix_documents_processing_status", "processing_status"),
    )

    device = relationship("Device", back_populates="documents")
    source = relationship("Source", back_populates="documents")
    versions = relationship("DocumentVersion", back_populates="document", order_by="DocumentVersion.version")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


# =============================================================================
# Document Version
# =============================================================================

class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)
    version = Column(Integer, nullable=False)
    content_hash = Column(String(128), nullable=False)
    file_size = Column(Integer, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_by_device = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_doc_version"),
    )

    document = relationship("Document", back_populates="versions")


# =============================================================================
# Document Chunk
# =============================================================================

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)

    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(128), nullable=False)
    token_count = Column(Integer, nullable=True)

    # Vector storage reference
    vector_point_id = Column(String(64), nullable=True)
    is_embedded = Column(Boolean, default=False)

    metadata_json = Column(Text, nullable=True)  # JSON string of chunk-level metadata

    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_content_hash", "content_hash"),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_index"),
    )

    document = relationship("Document", back_populates="chunks")


# =============================================================================
# Memory Record
# =============================================================================

class MemoryRecord(Base):
    """Represents a searchable knowledge unit in the system."""
    __tablename__ = "memory_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(64), nullable=False)
    source_id = Column(String(36), ForeignKey("sources.id"), nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=True)
    chunk_id = Column(String(36), ForeignKey("document_chunks.id"), nullable=True)

    content = Column(Text, nullable=False)
    content_hash = Column(String(128), nullable=False)
    record_type = Column(String(64), nullable=False)  # chunk, note, observation, record

    vector_point_id = Column(String(64), nullable=True)

    sensitivity = Column(String(32), nullable=False, default="internal")
    sync_status = Column(String(32), nullable=False, default="pending")

    version = Column(Integer, nullable=False, default=1)
    revision = Column(Integer, nullable=False, default=1)
    origin_device = Column(String(64), nullable=True)
    last_synced_revision = Column(Integer, nullable=True)

    metadata_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_memory_device_id", "device_id"),
        Index("ix_memory_sync_status", "sync_status"),
        Index("ix_memory_content_hash", "content_hash"),
    )


# =============================================================================
# Sync Item (Durable Queue)
# =============================================================================

class SyncItem(Base):
    """Persistent synchronization queue item."""
    __tablename__ = "sync_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    record_type = Column(String(64), nullable=False)  # document, chunk, memory_record
    record_id = Column(String(36), nullable=False)
    operation = Column(String(32), nullable=False)  # upsert, delete
    device_id = Column(String(64), nullable=False)

    status = Column(String(32), nullable=False, default="pending")

    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    next_retry_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    payload_json = Column(Text, nullable=True)  # Serialized point data for Qdrant upsert

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_sync_items_status", "status"),
        Index("ix_sync_items_next_retry", "next_retry_at"),
        Index("ix_sync_items_record", "record_type", "record_id"),
    )

    attempts = relationship("SyncAttempt", back_populates="sync_item", order_by="SyncAttempt.attempted_at")


# =============================================================================
# Sync Attempt
# =============================================================================

class SyncAttempt(Base):
    """Record of each synchronization attempt."""
    __tablename__ = "sync_attempts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    sync_item_id = Column(String(36), ForeignKey("sync_items.id"), nullable=False)

    status = Column(String(32), nullable=False)  # success, failed, conflict
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Float, nullable=True)

    attempted_at = Column(DateTime, default=utcnow)

    sync_item = relationship("SyncItem", back_populates="attempts")


# =============================================================================
# Conflict
# =============================================================================

class Conflict(Base):
    """Detected conflict between local and cloud versions."""
    __tablename__ = "conflicts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    record_type = Column(String(64), nullable=False)
    record_id = Column(String(36), nullable=False)

    local_revision = Column(Integer, nullable=False)
    local_content_hash = Column(String(128), nullable=False)
    local_updated_at = Column(DateTime, nullable=False)
    local_content_preview = Column(Text, nullable=True)
    local_device_id = Column(String(64), nullable=False)

    cloud_revision = Column(Integer, nullable=False)
    cloud_content_hash = Column(String(128), nullable=False)
    cloud_updated_at = Column(DateTime, nullable=False)
    cloud_content_preview = Column(Text, nullable=True)
    cloud_device_id = Column(String(64), nullable=True)

    status = Column(String(32), nullable=False, default="open")
    resolution = Column(String(64), nullable=True)
    resolved_by = Column(String(64), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_conflicts_status", "status"),
        Index("ix_conflicts_record", "record_type", "record_id"),
    )


# =============================================================================
# Audit Event
# =============================================================================

class AuditEvent(Base):
    """Immutable audit trail for all significant operations."""
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(64), ForeignKey("devices.id"), nullable=True)
    event_type = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=True)  # document, memory, sync, conflict, device
    entity_id = Column(String(36), nullable=True)

    description = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)

    operation_id = Column(String(36), nullable=True)
    request_id = Column(String(36), nullable=True)

    severity = Column(String(16), nullable=False, default="info")  # info, warning, error, critical

    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_audit_event_type", "event_type"),
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    device = relationship("Device", back_populates="audit_events")


# =============================================================================
# Conversation
# =============================================================================

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    device_id = Column(String(64), nullable=False)
    title = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    messages = relationship("ConversationMessage", back_populates="conversation", order_by="ConversationMessage.created_at")


# =============================================================================
# Conversation Message
# =============================================================================

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)

    role = Column(String(16), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)

    # RAG metadata
    sources_json = Column(Text, nullable=True)  # JSON: list of source citations
    retrieval_latency_ms = Column(Float, nullable=True)
    generation_latency_ms = Column(Float, nullable=True)
    total_latency_ms = Column(Float, nullable=True)
    source_count = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    conversation = relationship("Conversation", back_populates="messages")


# =============================================================================
# Embedding Metadata
# =============================================================================

class EmbeddingMetadata(Base):
    """Tracks embedding model info and vector dimensions."""
    __tablename__ = "embedding_metadata"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    model_name = Column(String(255), nullable=False)
    vector_dimension = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    total_embeddings_generated = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    last_used_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("model_name", name="uq_embedding_model"),
    )
