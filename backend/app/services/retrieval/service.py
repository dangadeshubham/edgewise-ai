"""
EDGEWISE AI — Retrieval Service

Shared retrieval layer used by both POST /api/search and POST /api/copilot/query.
Executes semantic vector search, resolves documents from SQLite, and returns
structured retrieval context. No duplication of retrieval logic between endpoints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.database import Document, DocumentChunk
from app.services.edge_memory import LocalMemorySearch, build_payload_filter

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class RetrievedChunk:
    """A single retrieved chunk with full metadata for RAG context assembly."""
    chunk_id: str
    document_id: str
    document_title: str
    filename: str
    source_name: Optional[str]
    document_type: Optional[str]
    device_id: Optional[str]
    content: str
    score: float
    chunk_index: Optional[int]
    page_start: Optional[int]
    page_end: Optional[int]
    content_hash: Optional[str]
    sensitivity: Optional[str]
    document_version_id: Optional[str]
    source_id: Optional[str]


@dataclass
class RetrievalResult:
    """Output of the retrieval pipeline."""
    query: str
    chunks: list[RetrievedChunk]
    total_retrieved: int
    embedding_latency_ms: float
    retrieval_latency_ms: float
    search_type: str = "semantic"
    score_threshold_applied: Optional[float] = None


class RetrievalService:
    """
    Unified retrieval service for semantic search.
    Both the search API and the RAG copilot use this service
    to avoid duplicating retrieval logic.
    """

    def __init__(self, db: AsyncSession, searcher: Optional[LocalMemorySearch] = None) -> None:
        self.db = db
        self.searcher = searcher or LocalMemorySearch()

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        min_score: Optional[float] = None,
        source_filter: Optional[list[str]] = None,
        device_filter: Optional[list[str]] = None,
        document_type_filter: Optional[list[str]] = None,
        sensitivity_filter: Optional[list[str]] = None,
    ) -> RetrievalResult:
        """
        Execute semantic search and resolve SQLite metadata.
        Returns structured RetrievedChunk objects with full traceability.
        """
        t0 = time.perf_counter()

        # 1. Build filter
        filter_obj = build_payload_filter(
            device_filter=device_filter,
            source_filter=source_filter,
            document_type_filter=document_type_filter,
            sensitivity_filter=sensitivity_filter,
        )

        # 2. Search with candidate pool
        searcher = self.searcher
        candidate_limit = max(limit * 5, 50)
        t_embed_start = time.perf_counter()
        search_result = searcher.search(
            query=query,
            limit=candidate_limit,
            filter_obj=filter_obj,
            score_threshold=min_score,
            use_hybrid=False,
        )
        embedding_latency_ms = search_result.retrieval_latency_ms

        # 3. Resolve chunks and documents from SQLite
        chunk_ids = {
            str(pt.payload.get("chunk_id", pt.id))
            for pt in search_result.results
            if pt.payload
        }

        chunk_map: dict[str, DocumentChunk] = {}
        if chunk_ids:
            chunk_stmt = (
                select(DocumentChunk)
                .options(
                    selectinload(DocumentChunk.document).selectinload(Document.source)
                )
                .where(DocumentChunk.id.in_(list(chunk_ids)))
            )
            chunk_records = (await self.db.execute(chunk_stmt)).scalars().all()
            chunk_map = {c.id: c for c in chunk_records}

        # 4. Filter: only include points that have an existing chunk & active document in SQLite
        valid_items = []
        for pt in search_result.results:
            payload = pt.payload or {}
            chunk_id = str(payload.get("chunk_id", pt.id))
            chunk_obj = chunk_map.get(chunk_id)

            if chunk_obj is None:
                continue
            doc = chunk_obj.document
            if doc is None or doc.deleted_at is not None:
                continue

            valid_items.append((pt, chunk_obj, doc))

        # 5. Sort by vector score descending
        sorted_results = sorted(
            valid_items,
            key=lambda item: float(item[0].score),
            reverse=True,
        )

        # 6. Build structured chunks
        chunks: list[RetrievedChunk] = []
        for pt, chunk_obj, doc in sorted_results:
            payload = pt.payload or {}
            source_name = doc.source.name if (doc and doc.source) else None

            chunks.append(RetrievedChunk(
                chunk_id=chunk_obj.id,
                document_id=doc.id,
                document_title=doc.title or doc.original_filename,
                filename=doc.original_filename,
                source_name=source_name,
                document_type=doc.document_type,
                device_id=doc.device_id,
                content=chunk_obj.content,
                score=float(pt.score),
                chunk_index=chunk_obj.chunk_index,
                page_start=payload.get("page_start"),
                page_end=payload.get("page_end"),
                content_hash=chunk_obj.content_hash,
                sensitivity=doc.sensitivity,
                document_version_id=payload.get("document_version_id"),
                source_id=doc.source_id,
            ))

            if len(chunks) >= limit:
                break

        total_latency_ms = (time.perf_counter() - t0) * 1000

        return RetrievalResult(
            query=query,
            chunks=chunks,
            total_retrieved=len(chunks),
            embedding_latency_ms=round(embedding_latency_ms, 2),
            retrieval_latency_ms=round(total_latency_ms, 2),
            search_type="semantic",
            score_threshold_applied=min_score,
        )
