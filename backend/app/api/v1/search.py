"""
EDGEWISE AI — Semantic Search API Endpoint

Executes semantic vector search against local Qdrant Edge memory.
Resolves document sources from SQLite and returns rich, verified search results.
"""

from __future__ import annotations

import time
from typing import Any
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.database import Document, DocumentChunk
from app.schemas.api import SearchRequest, SearchResponse, SearchResultItem
from app.services.edge_memory import (
    LocalMemorySearch,
    build_payload_filter,
)

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """
    Perform semantic search across local vector memory with payload filtering
    and SQLite source resolution.
    """
    t0 = time.perf_counter()

    try:
        # 1. Build native Qdrant Edge payload filter
        filter_obj = build_payload_filter(
            device_filter=request.device_filter,
            source_filter=request.source_filter,
            document_type_filter=request.document_type_filter,
            sensitivity_filter=request.sensitivity_filter,
        )

        # 2. Execute unified search across local Edge shards
        searcher = LocalMemorySearch()
        candidate_limit = max(request.limit * 5, 50)
        search_result = searcher.search(
            query=request.query,
            limit=candidate_limit,
            filter_obj=filter_obj,
            score_threshold=request.min_score,
            use_hybrid=False,
        )

        # 3. Resolve sources and documents from SQLite
        doc_ids = {
            pt.payload.get("document_id")
            for pt in search_result.results
            if pt.payload and pt.payload.get("document_id")
        }

        doc_map: dict[str, Document] = {}
        if doc_ids:
            doc_stmt = (
                select(Document)
                .options(selectinload(Document.source))
                .where(Document.id.in_(list(doc_ids)))
            )
            doc_records = (await db.execute(doc_stmt)).scalars().all()
            doc_map = {d.id: d for d in doc_records}

        # Prioritize active SQLite documents when scores are tied
        sorted_results = sorted(
            search_result.results,
            key=lambda pt: (
                float(pt.score),
                1 if (pt.payload and pt.payload.get("document_id") in doc_map) else 0,
            ),
            reverse=True,
        )

        # 4. Construct response items with verified scores and traceability
        items: list[SearchResultItem] = []
        for pt in sorted_results:
            payload = pt.payload or {}
            doc_id = payload.get("document_id")
            doc = doc_map.get(doc_id) if doc_id else None

            # Skip soft-deleted documents
            if doc is not None and doc.deleted_at is not None:
                continue

            chunk_id = str(payload.get("chunk_id", pt.id))
            text_content = payload.get("text", "")
            filename = (
                doc.original_filename
                if doc
                else payload.get("filename", "unknown")
            )
            doc_title = (
                (doc.title or doc.original_filename)
                if doc
                else (payload.get("title") or payload.get("filename"))
            )
            source_name = doc.source.name if (doc and doc.source) else None
            doc_type = (
                doc.document_type
                if doc
                else payload.get("document_type")
            )
            device_id = (
                doc.device_id
                if doc
                else payload.get("device_id")
            )

            # Metadata dictionary
            meta: dict[str, Any] = {
                "content_hash": payload.get("content_hash"),
                "sensitivity": payload.get("sensitivity"),
                "created_at": payload.get("created_at"),
                "source_id": payload.get("source_id"),
                "document_version_id": payload.get("document_version_id"),
                "page_start": payload.get("page_start"),
                "page_end": payload.get("page_end"),
            }

            items.append(
                SearchResultItem(
                    id=chunk_id,
                    content=text_content,
                    score=float(pt.score),
                    document_id=doc_id,
                    document_title=doc_title,
                    filename=filename,
                    source_name=source_name,
                    document_type=doc_type,
                    device_id=device_id,
                    chunk_index=payload.get("chunk_index"),
                    page_start=payload.get("page_start"),
                    page_end=payload.get("page_end"),
                    metadata=meta,
                )
            )

            if len(items) >= request.limit:
                break

        total_latency_ms = (time.perf_counter() - t0) * 1000

        return SearchResponse(
            query=request.query,
            results=items,
            total_results=len(items),
            retrieval_latency_ms=round(total_latency_ms, 2),
            search_type="semantic",
        )

    except Exception as exc:
        logger.error("search_failed", query=request.query, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic search failed: {str(exc)}",
        )
