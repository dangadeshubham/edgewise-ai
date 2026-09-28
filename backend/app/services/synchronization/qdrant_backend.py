"""EDGEWISE AI — Real Qdrant Server Synchronization Backend (Phase 7)

Implements real remote vector synchronization with Qdrant Server:
- Real Edge → Cloud vector upserts & deletes
- Idempotent operations via deterministic point IDs
- Smart sync eligibility & local placement enforcement
- Remote verification policy
- Snapshot creation & retrieval for Cloud → Edge synchronization
- Secrets strictly from configuration / environment
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional, Sequence

import structlog
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    Distance,
    PointIdsList,
    PointStruct,
    Record,
    SnapshotDescription,
    VectorParams,
)

from app.core.config import get_settings
from app.models.database import SyncItem
from app.services.edge_memory.point_id import generate_point_id_from_chunk_id
from app.services.embeddings import get_embedding_service
from app.services.synchronization.backend import SyncBackend, SyncResult
from app.services.synchronization.constants import (
    SyncErrorCategory,
    SyncState,
)

settings = get_settings()
logger = structlog.get_logger("edgewise.sync.qdrant_backend")


class QdrantServerSyncBackend(SyncBackend):
    """
    Real Qdrant Server synchronization backend.
    Communicates over HTTP/REST with the remote Qdrant cluster.
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection_name: Optional[str] = None,
        timeout: Optional[float] = None,
        check_compatibility: Optional[bool] = None,
    ) -> None:
        self.server_url = (server_url or settings.qdrant_server_url).rstrip("/")
        self.api_key = api_key or settings.qdrant_api_key
        self.collection_name = collection_name or settings.qdrant_collection_name
        self.timeout = timeout or settings.qdrant_timeout_seconds
        self.verify_remote = settings.qdrant_verify_remote
        self.check_compatibility = (
            check_compatibility if check_compatibility is not None else settings.qdrant_check_compatibility
        )

        # Real async and sync clients
        self.client = QdrantClient(
            url=self.server_url,
            api_key=self.api_key,
            timeout=self.timeout,
            prefer_grpc=False,
            check_compatibility=self.check_compatibility,
        )
        self.async_client = AsyncQdrantClient(
            url=self.server_url,
            api_key=self.api_key,
            timeout=self.timeout,
            prefer_grpc=False,
            check_compatibility=self.check_compatibility,
        )

    # =========================================================================
    # Health & Setup
    # =========================================================================

    async def health_check(self) -> bool:
        """Check whether Qdrant Server is reachable."""
        try:
            collections = await self.async_client.get_collections()
            return collections is not None
        except Exception as exc:
            logger.warning("qdrant_server_health_check_failed", error=str(exc))
            return False

    async def ensure_collection_exists(self) -> None:
        """Verify collection exists remotely or create with matching vector dimensions."""
        try:
            exists = await self.async_client.collection_exists(self.collection_name)
            if not exists:
                logger.info(
                    "creating_remote_qdrant_collection",
                    collection=self.collection_name,
                    dimension=settings.edge_vector_dimension,
                )
                await self.async_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.edge_vector_dimension,
                        distance=Distance.COSINE,
                    ),
                )
        except Exception as exc:
            logger.error("ensure_collection_failed", collection=self.collection_name, error=str(exc))
            raise

    # =========================================================================
    # Edge → Cloud: Upsert
    # =========================================================================

    async def upsert(self, item: SyncItem) -> SyncResult:
        """
        Upload a local knowledge item to Qdrant Server.
        Idempotent via deterministic point IDs.
        """
        start_time = time.perf_counter()

        # 1. Parse payload safely
        payload_data: dict[str, Any] = {}
        if item.payload_json:
            try:
                payload_data = json.loads(item.payload_json)
            except Exception as e:
                duration = (time.perf_counter() - start_time) * 1000
                return SyncResult(
                    success=False,
                    status=SyncState.FAILED,
                    error_category=SyncErrorCategory.VALIDATION_ERROR,
                    error_message=f"Invalid payload JSON: {e}",
                    duration_ms=round(duration, 2),
                )

        # 2. Smart Sync Eligibility (Phase 5 Placement Policy)
        sensitivity = payload_data.get("sensitivity", settings.default_sensitivity).lower()
        if sensitivity in settings.local_only_sensitivities_list:
            duration = (time.perf_counter() - start_time) * 1000
            logger.info(
                "sync_skipped_local_only",
                record_id=item.record_id,
                sensitivity=sensitivity,
                reason="Restricted by local-only placement policy",
            )
            return SyncResult(
                success=True,
                status=SyncState.SYNCED,
                duration_ms=round(duration, 2),
                details={
                    "local_only": True,
                    "reason": f"Sensitivity '{sensitivity}' is restricted to edge only",
                },
            )

        # 3. Extract or compute vector
        vector: Optional[list[float]] = payload_data.get("vector")
        text_content: Optional[str] = payload_data.get("content") or payload_data.get("text")

        if vector is None:
            if not text_content:
                duration = (time.perf_counter() - start_time) * 1000
                return SyncResult(
                    success=False,
                    status=SyncState.FAILED,
                    error_category=SyncErrorCategory.VALIDATION_ERROR,
                    error_message="Sync item payload contains neither vector nor text content",
                    duration_ms=round(duration, 2),
                )
            try:
                emb_service = get_embedding_service()
                vector = emb_service.embed_text(text_content)
            except Exception as e:
                duration = (time.perf_counter() - start_time) * 1000
                return SyncResult(
                    success=False,
                    status=SyncState.FAILED,
                    error_category=SyncErrorCategory.PERMANENT_FAILURE,
                    error_message=f"Embedding generation failed: {e}",
                    duration_ms=round(duration, 2),
                )

        # 4. Generate deterministic point ID
        point_id = generate_point_id_from_chunk_id(item.record_id)

        # 5. Build clean remote payload
        remote_payload = {
            "record_id": item.record_id,
            "record_type": item.record_type,
            "revision": item.revision or 1,
            "content_hash": item.content_hash or payload_data.get("content_hash"),
            "device_id": item.device_id,
            "origin_device": payload_data.get("origin_device", item.device_id),
            "sensitivity": sensitivity,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            "text": text_content,
            "metadata": payload_data.get("metadata", {}),
        }

        point = PointStruct(
            id=point_id,
            vector=vector,
            payload=remote_payload,
        )

        # 6. Execute remote upsert
        try:
            await self.ensure_collection_exists()

            update_res = await self.async_client.upsert(
                collection_name=self.collection_name,
                points=[point],
                wait=True,
            )

            # 7. Optional remote verification
            if self.verify_remote:
                retrieved = await self.async_client.retrieve(
                    collection_name=self.collection_name,
                    ids=[point_id],
                    with_payload=False,
                )
                if not retrieved:
                    duration = (time.perf_counter() - start_time) * 1000
                    return SyncResult(
                        success=False,
                        status=SyncState.FAILED,
                        error_category=SyncErrorCategory.REMOTE_UNAVAILABLE,
                        error_message="Remote verification failed: point not found after upsert",
                        duration_ms=round(duration, 2),
                    )

            duration = (time.perf_counter() - start_time) * 1000
            logger.info(
                "qdrant_server_upsert_success",
                record_id=item.record_id,
                point_id=point_id,
                collection=self.collection_name,
                duration_ms=round(duration, 2),
            )
            return SyncResult(
                success=True,
                status=SyncState.SYNCED,
                duration_ms=round(duration, 2),
                remote_version=item.revision or 1,
                details={"point_id": point_id, "operation_status": str(update_res.status)},
            )

        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            cat, msg = self._classify_exception(exc)
            logger.error(
                "qdrant_server_upsert_failed",
                record_id=item.record_id,
                error=msg,
                category=cat.value,
                duration_ms=round(duration, 2),
            )
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=cat,
                error_message=msg,
                duration_ms=round(duration, 2),
            )

    # =========================================================================
    # Edge → Cloud: Delete
    # =========================================================================

    async def delete(self, item: SyncItem) -> SyncResult:
        """
        Propagate logical delete to Qdrant Server.
        Idempotent via deterministic point IDs.
        """
        start_time = time.perf_counter()
        point_id = generate_point_id_from_chunk_id(item.record_id)

        try:
            await self.ensure_collection_exists()

            update_res = await self.async_client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=[point_id]),
                wait=True,
            )

            duration = (time.perf_counter() - start_time) * 1000
            logger.info(
                "qdrant_server_delete_success",
                record_id=item.record_id,
                point_id=point_id,
                collection=self.collection_name,
                duration_ms=round(duration, 2),
            )
            return SyncResult(
                success=True,
                status=SyncState.SYNCED,
                duration_ms=round(duration, 2),
                details={"point_id": point_id, "operation_status": str(update_res.status)},
            )

        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            cat, msg = self._classify_exception(exc)
            logger.error(
                "qdrant_server_delete_failed",
                record_id=item.record_id,
                error=msg,
                category=cat.value,
            )
            return SyncResult(
                success=False,
                status=SyncState.FAILED,
                error_category=cat,
                error_message=msg,
                duration_ms=round(duration, 2),
            )

    # =========================================================================
    # Cloud → Edge: Snapshots & Point Retrieval
    # =========================================================================

    async def create_snapshot(self) -> SnapshotDescription:
        """Create a full snapshot on Qdrant Server for Cloud → Edge synchronization."""
        await self.ensure_collection_exists()
        snap = await self.async_client.create_snapshot(collection_name=self.collection_name, wait=True)
        if snap is None:
            raise RuntimeError("Qdrant Server failed to create collection snapshot")
        return snap

    async def list_snapshots(self) -> list[SnapshotDescription]:
        """List snapshots for the collection on Qdrant Server."""
        await self.ensure_collection_exists()
        return await self.async_client.list_snapshots(collection_name=self.collection_name)

    def download_snapshot(self, snapshot_name: str, target_path: Path) -> Path:
        """
        Download a snapshot archive from Qdrant Server to local disk.
        Uses HTTP GET /collections/{collection_name}/snapshots/{snapshot_name}.
        """
        url = f"{self.server_url}/collections/{self.collection_name}/snapshots/{snapshot_name}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["api-key"] = self.api_key

        req = urllib.request.Request(url, headers=headers)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with urllib.request.urlopen(req, timeout=30.0) as resp, open(target_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)

        logger.info(
            "qdrant_snapshot_downloaded",
            snapshot=snapshot_name,
            size_bytes=target_path.stat().st_size,
            path=str(target_path),
        )
        return target_path

    async def fetch_server_points(self, limit: int = 500) -> list[Record]:
        """Fetch records with payload and vectors from Qdrant Server."""
        await self.ensure_collection_exists()
        res = await self.async_client.scroll(
            collection_name=self.collection_name,
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )
        records, _ = res
        return records

    # =========================================================================
    # Error Classification Helper
    # =========================================================================

    def _classify_exception(self, exc: Exception) -> tuple[SyncErrorCategory, str]:
        """Categorize Qdrant Client / network exceptions."""
        exc_str = str(exc)
        # Redact any accidental tokens in logs
        if self.api_key and self.api_key in exc_str:
            exc_str = exc_str.replace(self.api_key, "[REDACTED]")

        exc_type = type(exc).__name__

        if "401" in exc_str or "403" in exc_str or "unauthorized" in exc_str.lower():
            return SyncErrorCategory.AUTHENTICATION_ERROR, f"Authentication failed: {exc_str}"
        elif "429" in exc_str or "rate limit" in exc_str.lower():
            return SyncErrorCategory.RATE_LIMITED, f"Rate limited: {exc_str}"
        elif "timeout" in exc_str.lower() or "timed out" in exc_str.lower():
            return SyncErrorCategory.TIMEOUT, f"Request timed out: {exc_str}"
        elif "connect" in exc_str.lower() or "10061" in exc_str or "refused" in exc_str.lower():
            return SyncErrorCategory.REMOTE_UNAVAILABLE, f"Qdrant server unavailable: {exc_str}"
        elif "validation" in exc_str.lower() or "bad request" in exc_str.lower():
            return SyncErrorCategory.VALIDATION_ERROR, f"Payload validation error: {exc_str}"
        else:
            return SyncErrorCategory.TRANSIENT_NETWORK_ERROR, f"Network error ({exc_type}): {exc_str}"
