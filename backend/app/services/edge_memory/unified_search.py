"""
EDGEWISE AI — Unified Local Memory Search

Queries mutable shard and immutable shard (when populated), merges and deduplicates results,
and reports true shard contributions without fabricating immutable data.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Optional
import structlog
import qdrant_edge

from app.services.edge_memory.service import EdgeMemoryService, get_edge_memory_service
from app.services.embeddings.service import EmbeddingService, get_embedding_service

logger = structlog.get_logger(__name__)


@dataclass
class UnifiedSearchResult:
    """Output of unified local memory search across edge shards."""
    query: str
    results: list[qdrant_edge.ScoredPoint]
    total_results: int
    mutable_results_count: int
    immutable_results_count: int
    immutable_shard_queried: bool
    retrieval_latency_ms: float
    search_type: str


class LocalMemorySearch:
    """
    Unified local memory search orchestrator.
    Executes semantic search across local Edge shards.
    """

    def __init__(
        self,
        memory_service: Optional[EdgeMemoryService] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self.memory_service = memory_service or get_edge_memory_service()
        self.embedding_service = embedding_service or get_embedding_service()

    def search(
        self,
        query: str,
        limit: int = 10,
        filter_obj: Optional[qdrant_edge.Filter] = None,
        score_threshold: Optional[float] = None,
        use_hybrid: bool = False,
    ) -> UnifiedSearchResult:
        """
        Execute semantic search across local mutable and immutable shards.
        Merges results and deduplicates by logical chunk identifier.
        """
        t0 = time.perf_counter()

        # 1. Generate query embedding
        query_vector = self.embedding_service.embed_text(query)

        # 2. Query mutable shard (always present)
        mutable_hits = self.memory_service.query_points(
            query_vector=query_vector,
            limit=limit,
            filter_obj=filter_obj,
            score_threshold=score_threshold,
            query_text=query if use_hybrid else None,
            shard_type="mutable",
            use_hybrid=use_hybrid,
        )

        # 3. Query immutable shard only if populated
        immutable_hits: list[qdrant_edge.ScoredPoint] = []
        immutable_queried = False

        if self.memory_service.has_immutable_shard():
            try:
                immutable_hits = self.memory_service.query_points(
                    query_vector=query_vector,
                    limit=limit,
                    filter_obj=filter_obj,
                    score_threshold=score_threshold,
                    query_text=query if use_hybrid else None,
                    shard_type="immutable",
                    use_hybrid=use_hybrid,
                )
                immutable_queried = True
            except Exception as exc:
                logger.warning("immutable_shard_query_failed", error=str(exc))
                immutable_hits = []

        # 4. Merge and deduplicate
        # Deduplication key is chunk_id or point id
        seen: dict[str, qdrant_edge.ScoredPoint] = {}

        # Prioritize mutable, but if both have the same chunk, keep the higher score
        for pt in mutable_hits:
            key = str(pt.payload.get("chunk_id", pt.id) if pt.payload else pt.id)
            seen[key] = pt

        for pt in immutable_hits:
            key = str(pt.payload.get("chunk_id", pt.id) if pt.payload else pt.id)
            if key not in seen or pt.score > seen[key].score:
                seen[key] = pt

        # Sort descending by score
        merged = sorted(seen.values(), key=lambda x: x.score, reverse=True)
        final_results = merged[:limit]

        latency_ms = (time.perf_counter() - t0) * 1000

        return UnifiedSearchResult(
            query=query,
            results=final_results,
            total_results=len(final_results),
            mutable_results_count=len(mutable_hits),
            immutable_results_count=len(immutable_hits),
            immutable_shard_queried=immutable_queried,
            retrieval_latency_ms=round(latency_ms, 2),
            search_type="hybrid" if use_hybrid else "semantic",
        )
