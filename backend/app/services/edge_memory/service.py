"""
EDGEWISE AI — Qdrant Edge Memory Service

Encapsulates all interaction with native embedded Qdrant Edge shards.
Isolates Qdrant implementation details from the rest of the application.
Provides deterministic vector upsert, native BM25 sparse indexing,
hybrid and dense querying, filtering, retrieval, flushing, and persistence.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import threading
from typing import Any, Optional, Sequence
import structlog
import qdrant_edge

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class EdgeMemoryError(Exception):
    """Base exception for Edge Memory errors."""
    pass


class ShardLoadError(EdgeMemoryError):
    """Raised when an edge shard cannot be loaded."""
    pass


class ShardCorruptError(EdgeMemoryError):
    """Raised when an edge shard directory is corrupted or unreadable."""
    pass


class VectorDimensionError(EdgeMemoryError):
    """Raised when vector dimension does not match shard configuration."""
    pass


class EdgeMemoryService:
    """
    Local Semantic Memory Service powered by Qdrant Edge.
    Manages mutable and immutable edge shards on disk.
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        mutable_dir: Optional[str] = None,
        immutable_dir: Optional[str] = None,
        dimension: Optional[int] = None,
        distance: Optional[str] = None,
    ) -> None:
        settings = get_settings()

        self.data_dir: Path = Path(data_dir or settings.edge_data_dir)
        self.mutable_dir: Path = Path(mutable_dir or settings.edge_mutable_dir)
        self.immutable_dir: Path = Path(immutable_dir or settings.edge_immutable_dir)
        self.dimension: int = dimension or settings.edge_vector_dimension
        self.distance_name: str = distance or settings.edge_distance

        # Map distance string to enum
        dist_map = {
            "cosine": qdrant_edge.Distance.Cosine,
            "dot": qdrant_edge.Distance.Dot,
            "euclid": qdrant_edge.Distance.Euclid,
            "manhattan": qdrant_edge.Distance.Manhattan,
        }
        self.distance_enum = dist_map.get(self.distance_name.lower(), qdrant_edge.Distance.Cosine)

        # Thread lock for thread-safe access to embedded shards
        self._lock = threading.RLock()

        # Shard references
        self._mutable_shard: Optional[qdrant_edge.EdgeShard] = None
        self._immutable_shard: Optional[qdrant_edge.EdgeShard] = None

        # Last flush timestamp
        self._last_flush_time: Optional[datetime.datetime] = None

        # Native BM25 sparse model
        self._bm25 = qdrant_edge.Bm25()

        # Ensure base directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.mutable_dir.mkdir(parents=True, exist_ok=True)
        self.immutable_dir.mkdir(parents=True, exist_ok=True)

        # Create standard shard config
        self._config = self._build_config()

        # Eagerly initialize mutable shard
        self._init_mutable_shard()

    def _build_config(self) -> qdrant_edge.EdgeConfig:
        """Build standard EdgeConfig with dense and BM25 sparse vectors."""
        dense_params = qdrant_edge.EdgeVectorParams(
            size=self.dimension,
            distance=self.distance_enum,
        )
        sparse_params = qdrant_edge.EdgeSparseVectorParams(
            modifier=qdrant_edge.Modifier.Idf,
        )
        return qdrant_edge.EdgeConfig(
            vectors={"dense": dense_params},
            sparse_vectors={"bm25": sparse_params},
        )

    def _init_mutable_shard(self) -> None:
        """Initialize or load mutable shard from disk."""
        with self._lock:
            try:
                self.mutable_dir.mkdir(parents=True, exist_ok=True)
                wal_dir = self.mutable_dir / "wal"
                has_data = wal_dir.exists() or any(self.mutable_dir.iterdir())

                if not has_data:
                    logger.info("creating_mutable_edge_shard", path=str(self.mutable_dir))
                    self._mutable_shard = qdrant_edge.EdgeShard.create(
                        str(self.mutable_dir),
                        self._config,
                    )
                else:
                    logger.info("loading_mutable_edge_shard", path=str(self.mutable_dir))
                    try:
                        self._mutable_shard = qdrant_edge.EdgeShard.load(
                            str(self.mutable_dir),
                            self._config,
                        )
                    except Exception:
                        self._mutable_shard = qdrant_edge.EdgeShard.load(str(self.mutable_dir))

                self._ensure_payload_indexes(self._mutable_shard)

            except Exception as exc:
                logger.error("failed_to_initialize_mutable_shard", error=str(exc))
                raise ShardLoadError(f"Failed to initialize mutable shard at {self.mutable_dir}: {exc}") from exc

    def _ensure_payload_indexes(self, shard: qdrant_edge.EdgeShard) -> None:
        """Create payload indexes on common filtering fields."""
        fields_to_index = ["document_id", "device_id", "source_id", "document_type", "sensitivity"]
        for field in fields_to_index:
            try:
                op = qdrant_edge.UpdateOperation.create_field_index(
                    field,
                    qdrant_edge.PayloadSchemaType.Keyword,
                )
                shard.update(op)
            except Exception:
                # Field index might already exist or not supported
                pass

    def _get_shard(self, shard_type: str = "mutable") -> qdrant_edge.EdgeShard:
        """Get active shard instance, loading if necessary."""
        with self._lock:
            if shard_type == "mutable":
                if self._mutable_shard is None:
                    self._init_mutable_shard()
                return self._mutable_shard

            elif shard_type == "immutable":
                if self._immutable_shard is None:
                    if not self.has_immutable_shard():
                        raise ShardLoadError(f"Immutable shard at {self.immutable_dir} has not been populated.")
                    try:
                        self._immutable_shard = qdrant_edge.EdgeShard.load(str(self.immutable_dir))
                    except Exception as exc:
                        raise ShardLoadError(f"Failed to load immutable shard at {self.immutable_dir}: {exc}") from exc
                return self._immutable_shard

            else:
                raise ValueError(f"Unknown shard_type: '{shard_type}'. Expected 'mutable' or 'immutable'.")

    def has_immutable_shard(self) -> bool:
        """Check if immutable shard exists and has segment data on disk."""
        if not self.immutable_dir.exists():
            return False
        wal = self.immutable_dir / "wal"
        return wal.exists() or any(self.immutable_dir.iterdir())

    def init_immutable_shard(self) -> None:
        """Explicitly create empty immutable shard on disk."""
        with self._lock:
            self.immutable_dir.mkdir(parents=True, exist_ok=True)
            if self._immutable_shard is not None:
                self._immutable_shard.close()
                self._immutable_shard = None
            self._immutable_shard = qdrant_edge.EdgeShard.create(
                str(self.immutable_dir),
                self._config,
            )
            self._ensure_payload_indexes(self._immutable_shard)

    def upsert_chunk(
        self,
        point_id: str,
        dense_vector: list[float],
        text: str,
        payload: dict[str, Any],
        shard_type: str = "mutable",
    ) -> None:
        """
        Upsert a document chunk vector with dense embedding and native BM25 sparse vector.
        """
        if len(dense_vector) != self.dimension:
            raise VectorDimensionError(
                f"Vector dimension {len(dense_vector)} does not match configured dimension {self.dimension}."
            )

        with self._lock:
            shard = self._get_shard(shard_type)
            doc_sparse = self._bm25.embed_document(text or " ")

            vector_dict = {
                "dense": dense_vector,
                "bm25": doc_sparse,
            }

            full_payload = dict(payload)
            full_payload["text"] = text

            point = qdrant_edge.Point(
                id=point_id,
                vector=vector_dict,
                payload=full_payload,
            )

            op = qdrant_edge.UpdateOperation.upsert_points([point])
            shard.update(op)

    def upsert_points(
        self,
        points: Sequence[qdrant_edge.Point],
        shard_type: str = "mutable",
    ) -> None:
        """Upsert a batch of prepared Point objects."""
        if not points:
            return
        with self._lock:
            shard = self._get_shard(shard_type)
            op = qdrant_edge.UpdateOperation.upsert_points(list(points))
            shard.update(op)

    def delete_points(
        self,
        point_ids: Sequence[str | int],
        shard_type: str = "mutable",
    ) -> None:
        """Delete points by their deterministic IDs."""
        if not point_ids:
            return
        with self._lock:
            shard = self._get_shard(shard_type)
            op = qdrant_edge.UpdateOperation.delete_points(list(point_ids))
            shard.update(op)

    def delete_points_by_filter(
        self,
        filter_obj: qdrant_edge.Filter,
        shard_type: str = "mutable",
    ) -> None:
        """Delete points matching payload filter."""
        with self._lock:
            shard = self._get_shard(shard_type)
            op = qdrant_edge.UpdateOperation.delete_points_by_filter(filter_obj)
            shard.update(op)

    def query_points(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter_obj: Optional[qdrant_edge.Filter] = None,
        score_threshold: Optional[float] = None,
        query_text: Optional[str] = None,
        shard_type: str = "mutable",
        use_hybrid: bool = False,
    ) -> list[qdrant_edge.ScoredPoint]:
        """
        Query points by dense vector (or hybrid dense+BM25) with payload filtering.
        """
        if len(query_vector) != self.dimension:
            raise VectorDimensionError(
                f"Query vector dimension {len(query_vector)} does not match shard dimension {self.dimension}."
            )

        with self._lock:
            shard = self._get_shard(shard_type)

            dense_q = qdrant_edge.Query.Nearest(query_vector, using="dense")

            if use_hybrid and query_text and query_text.strip():
                # Hybrid RRF search
                sparse_q = qdrant_edge.Query.Nearest(
                    self._bm25.embed_query(query_text),
                    using="bm25",
                )
                prefetch_dense = qdrant_edge.Prefetch(limit=limit * 2, query=dense_q, filter=filter_obj)
                prefetch_sparse = qdrant_edge.Prefetch(limit=limit * 2, query=sparse_q, filter=filter_obj)

                req = qdrant_edge.QueryRequest(
                    limit=limit,
                    prefetches=[prefetch_dense, prefetch_sparse],
                    query=qdrant_edge.Fusion.Rrf(k=60),
                    filter=filter_obj,
                    score_threshold=score_threshold,
                    with_payload=True,
                )
            else:
                # Dense nearest neighbor query (exact cosine similarity score)
                req = qdrant_edge.QueryRequest(
                    limit=limit,
                    query=dense_q,
                    filter=filter_obj,
                    score_threshold=score_threshold,
                    with_payload=True,
                )

            return shard.query(req)

    def retrieve_points(
        self,
        point_ids: Sequence[str | int],
        shard_type: str = "mutable",
        with_payload: bool = True,
        with_vector: bool = False,
    ) -> list[qdrant_edge.Record]:
        """Retrieve points by IDs with optional payload and vector."""
        if not point_ids:
            return []
        with self._lock:
            shard = self._get_shard(shard_type)
            return shard.retrieve(list(point_ids), with_payload=with_payload, with_vector=with_vector)

    def count_points(self, shard_type: str = "mutable") -> int:
        """Return total point count in specified shard."""
        with self._lock:
            try:
                shard = self._get_shard(shard_type)
                info = shard.info()
                return info.points_count
            except ShardLoadError:
                return 0
            except Exception as exc:
                logger.warning("count_points_error", shard_type=shard_type, error=str(exc))
                return 0

    def get_shard_info(self, shard_type: str = "mutable") -> dict[str, Any]:
        """Inspect shard health and metadata."""
        with self._lock:
            target_dir = self.mutable_dir if shard_type == "mutable" else self.immutable_dir
            try:
                shard = self._get_shard(shard_type)
                info = shard.info()
                return {
                    "shard_type": shard_type,
                    "status": "ready",
                    "path": str(target_dir),
                    "points_count": info.points_count,
                    "segments_count": info.segments_count,
                    "indexed_vectors_count": getattr(info, "indexed_vectors_count", 0),
                    "last_flush": self._last_flush_time.isoformat() if self._last_flush_time else None,
                }
            except ShardLoadError:
                return {
                    "shard_type": shard_type,
                    "status": "unpopulated",
                    "path": str(target_dir),
                    "points_count": 0,
                    "segments_count": 0,
                    "indexed_vectors_count": 0,
                    "last_flush": None,
                }
            except Exception as exc:
                return {
                    "shard_type": shard_type,
                    "status": "error",
                    "path": str(target_dir),
                    "error": str(exc),
                    "points_count": 0,
                    "segments_count": 0,
                }

    def flush(self, shard_type: str = "mutable") -> None:
        """Flush in-memory segments to disk."""
        with self._lock:
            shard = self._get_shard(shard_type)
            shard.flush()
            self._last_flush_time = datetime.datetime.now(datetime.timezone.utc)
            logger.info("edge_shard_flushed", shard_type=shard_type, path=str(self.mutable_dir if shard_type == "mutable" else self.immutable_dir))

    def close(self, shard_type: Optional[str] = None) -> None:
        """Close shard(s)."""
        with self._lock:
            if shard_type is None or shard_type == "mutable":
                if self._mutable_shard is not None:
                    try:
                        self._mutable_shard.flush()
                        self._mutable_shard.close()
                    except Exception:
                        pass
                    self._mutable_shard = None

            if shard_type is None or shard_type == "immutable":
                if self._immutable_shard is not None:
                    try:
                        self._immutable_shard.flush()
                        self._immutable_shard.close()
                    except Exception:
                        pass
                    self._immutable_shard = None

    def reopen(self, shard_type: str = "mutable") -> None:
        """Close and reopen a shard from disk."""
        with self._lock:
            self.close(shard_type)
            if shard_type == "mutable":
                self._init_mutable_shard()
            elif shard_type == "immutable":
                self._immutable_shard = qdrant_edge.EdgeShard.load(str(self.immutable_dir))

    def snapshot_manifest(self, shard_type: str = "mutable") -> dict[str, Any]:
        """Return snapshot manifest for replication and synchronization."""
        with self._lock:
            shard = self._get_shard(shard_type)
            return shard.snapshot_manifest()

    def optimize(self, shard_type: str = "mutable") -> None:
        """Trigger segment optimization."""
        with self._lock:
            shard = self._get_shard(shard_type)
            shard.optimize()

    def is_healthy(self, shard_type: str = "mutable") -> bool:
        """Check if shard is accessible, can report info, and can be queried."""
        with self._lock:
            try:
                shard = self._get_shard(shard_type)
                info = shard.info()
                return info is not None
            except Exception:
                return False

    @property
    def last_flush_time(self) -> Optional[datetime.datetime]:
        return self._last_flush_time


# Singleton instance
_edge_memory_service: Optional[EdgeMemoryService] = None


def get_edge_memory_service() -> EdgeMemoryService:
    """Return singleton EdgeMemoryService."""
    global _edge_memory_service
    if _edge_memory_service is None:
        _edge_memory_service = EdgeMemoryService()
    return _edge_memory_service


def reset_edge_memory_service() -> None:
    """Reset the singleton instance (useful for testing)."""
    global _edge_memory_service
    if _edge_memory_service is not None:
        try:
            _edge_memory_service.close()
        except Exception:
            pass
    _edge_memory_service = None
