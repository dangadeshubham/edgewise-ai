"""Initial schema — all tables

Revision ID: 001_initial
Revises: None
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- devices ---
    op.create_table(
        "devices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("site", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("software_version", sa.String(64), nullable=True),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("last_sync", sa.DateTime, nullable=True),
        sa.Column("pending_changes", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- sources ---
    op.create_table(
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("document_type", sa.String(64), nullable=True),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.Column("sensitivity", sa.String(32), nullable=False, server_default="internal"),
        sa.Column("sync_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("origin_device", sa.String(64), nullable=True),
        sa.Column("last_synced_revision", sa.Integer, nullable=True),
        sa.Column("chunk_count", sa.Integer, server_default="0"),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.Column("indexed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_device_id", "documents", ["device_id"])
    op.create_index("ix_documents_sync_status", "documents", ["sync_status"])
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])

    # --- document_versions ---
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("change_summary", sa.Text, nullable=True),
        sa.Column("created_by_device", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_unique_constraint("uq_doc_version", "document_versions", ["document_id", "version"])

    # --- document_chunks ---
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("vector_point_id", sa.String(64), nullable=True),
        sa.Column("is_embedded", sa.Boolean, server_default="0"),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_content_hash", "document_chunks", ["content_hash"])
    op.create_unique_constraint("uq_chunk_index", "document_chunks", ["document_id", "chunk_index"])

    # --- memory_records ---
    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("document_chunks.id"), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("record_type", sa.String(64), nullable=False),
        sa.Column("vector_point_id", sa.String(64), nullable=True),
        sa.Column("sensitivity", sa.String(32), nullable=False, server_default="internal"),
        sa.Column("sync_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("origin_device", sa.String(64), nullable=True),
        sa.Column("last_synced_revision", sa.Integer, nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_memory_device_id", "memory_records", ["device_id"])
    op.create_index("ix_memory_sync_status", "memory_records", ["sync_status"])
    op.create_index("ix_memory_content_hash", "memory_records", ["content_hash"])

    # --- sync_items ---
    op.create_table(
        "sync_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("record_type", sa.String(64), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, server_default="0"),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("max_retries", sa.Integer, server_default="5"),
        sa.Column("next_retry_at", sa.DateTime, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_sync_items_status", "sync_items", ["status"])
    op.create_index("ix_sync_items_next_retry", "sync_items", ["next_retry_at"])
    op.create_index("ix_sync_items_record", "sync_items", ["record_type", "record_id"])

    # --- sync_attempts ---
    op.create_table(
        "sync_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sync_item_id", sa.String(36), sa.ForeignKey("sync_items.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("attempted_at", sa.DateTime, nullable=False),
    )

    # --- conflicts ---
    op.create_table(
        "conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("record_type", sa.String(64), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("local_revision", sa.Integer, nullable=False),
        sa.Column("local_content_hash", sa.String(128), nullable=False),
        sa.Column("local_updated_at", sa.DateTime, nullable=False),
        sa.Column("local_content_preview", sa.Text, nullable=True),
        sa.Column("local_device_id", sa.String(64), nullable=False),
        sa.Column("cloud_revision", sa.Integer, nullable=False),
        sa.Column("cloud_content_hash", sa.String(128), nullable=False),
        sa.Column("cloud_updated_at", sa.DateTime, nullable=False),
        sa.Column("cloud_content_preview", sa.Text, nullable=True),
        sa.Column("cloud_device_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(64), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_conflicts_status", "conflicts", ["status"])
    op.create_index("ix_conflicts_record", "conflicts", ["record_type", "record_id"])

    # --- audit_events ---
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), sa.ForeignKey("devices.id"), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("details_json", sa.Text, nullable=True),
        sa.Column("operation_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_audit_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id"])

    # --- conversations ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # --- conversation_messages ---
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sources_json", sa.Text, nullable=True),
        sa.Column("retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("generation_latency_ms", sa.Float, nullable=True),
        sa.Column("total_latency_ms", sa.Float, nullable=True),
        sa.Column("source_count", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # --- embedding_metadata ---
    op.create_table(
        "embedding_metadata",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("vector_dimension", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="1"),
        sa.Column("total_embeddings_generated", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_used_at", sa.DateTime, nullable=False),
    )
    op.create_unique_constraint("uq_embedding_model", "embedding_metadata", ["model_name"])


def downgrade() -> None:
    op.drop_table("embedding_metadata")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("audit_events")
    op.drop_table("conflicts")
    op.drop_table("sync_attempts")
    op.drop_table("sync_items")
    op.drop_table("memory_records")
    op.drop_table("document_chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("devices")
