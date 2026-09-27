"""
EDGEWISE AI — Application Configuration

All configuration is driven by environment variables.
No secrets are hardcoded. See .env.example for reference.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sensitivity(str, Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class SyncStatus(str, Enum):
    """Synchronization state machine."""
    PENDING = "pending"
    PROCESSING = "processing"
    SYNCED = "synced"
    FAILED = "failed"
    CONFLICT = "conflict"
    DELETED = "deleted"
    LOCAL_ONLY = "local_only"


class ConnectivityState(str, Enum):
    """System connectivity states."""
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    SYNCING = "syncing"


class ProcessingStatus(str, Enum):
    """Document processing pipeline status."""
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class ConflictStatus(str, Enum):
    """Conflict resolution states."""
    OPEN = "open"
    RESOLVED_KEEP_LOCAL = "resolved_keep_local"
    RESOLVED_KEEP_CLOUD = "resolved_keep_cloud"
    RESOLVED_MERGED = "resolved_merged"
    RESOLVED_MANUAL = "resolved_manual"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Device ---
    device_id: str = "edge-device-001"
    device_name: str = "Site-A Field Terminal"
    device_site: str = "site-alpha"

    # --- Backend Server ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_log_level: str = "info"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- SQLite ---
    sqlite_database_url: str = "sqlite+aiosqlite:///./data/sqlite/edgewise.db"

    # --- Qdrant Edge ---
    edge_mutable_shard_path: str = "./data/qdrant_edge/mutable"
    edge_immutable_shard_path: str = "./data/qdrant_edge/immutable"
    edge_vector_name: str = "dense"
    edge_sparse_vector_name: str = "sparse_bm25"

    # --- Qdrant Server ---
    qdrant_server_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    qdrant_collection_name: str = "edgewise-knowledge"

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout: int = 120

    # --- Embedding ---
    embedding_model_name: str = "all-MiniLM-L6-v2"

    # --- Document Ingestion ---
    max_upload_size_mb: int = 50
    allowed_file_types: str = ".pdf,.txt,.md,.json,.docx"
    chunk_size: int = 512
    chunk_overlap: int = 64

    # --- Synchronization ---
    sync_batch_size: int = 50
    sync_retry_max: int = 5
    sync_retry_base_delay_seconds: float = 2.0
    sync_interval_seconds: int = 300

    # --- Data Placement ---
    default_sensitivity: str = "internal"
    sync_eligible_sensitivities: str = "public,internal"
    local_only_sensitivities: str = "confidential,restricted"

    # --- File Storage ---
    upload_dir: str = "./data/uploads"
    processed_dir: str = "./data/processed"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_file_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_file_types.split(",") if t.strip()]

    @property
    def sync_eligible_sensitivities_list(self) -> list[str]:
        return [s.strip() for s in self.sync_eligible_sensitivities.split(",")]

    @property
    def local_only_sensitivities_list(self) -> list[str]:
        return [s.strip() for s in self.local_only_sensitivities.split(",")]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create required data directories if they don't exist."""
        for dir_path in [
            self.upload_dir,
            self.processed_dir,
            self.edge_mutable_shard_path,
            self.edge_immutable_shard_path,
            Path(self.sqlite_database_url.replace("sqlite+aiosqlite:///", "")).parent,
        ]:
            Path(dir_path).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory function for settings singleton."""
    return Settings()
