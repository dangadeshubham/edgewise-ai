"""
EDGEWISE AI — AI Copilot API

RAG-powered question answering using local Qdrant Edge retrieval + Ollama generation.
All responses are grounded in retrieved evidence. No fabricated answers or fake metrics.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.schemas.api import (
    CopilotQueryRequest,
    CopilotQueryResponse,
    EvidenceInfo,
    SourceCitation,
)
from app.services.llm import (
    OllamaUnavailableError,
    OllamaModelNotFoundError,
    OllamaGenerationError,
    OllamaTimeoutError,
)
from app.services.rag import RAGService

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/query", response_model=CopilotQueryResponse, dependencies=[Depends(rate_limit("copilot"))])
async def copilot_query(
    request: CopilotQueryRequest,
    db: AsyncSession = Depends(get_db),
) -> CopilotQueryResponse:
    """
    Ask a question and receive a grounded answer with source citations.
    Uses local Qdrant Edge retrieval + Ollama LLM generation.
    """
    try:
        rag_service = RAGService(db)
        result = await rag_service.query(
            question=request.question,
            conversation_id=request.conversation_id,
            max_sources=request.max_sources,
        )

        # Convert RAG citations to API schema
        api_sources = [
            SourceCitation(
                document_id=s.document_id,
                document_title=s.document_title,
                chunk_id=s.chunk_id,
                filename=s.filename,
                source_name=s.source_name,
                content_preview=s.content_preview,
                relevance_score=s.score,
                chunk_index=s.chunk_index,
                page_start=s.page_start,
                page_end=s.page_end,
            )
            for s in result.sources
        ]

        evidence = EvidenceInfo(
            chunk_count=result.chunk_count,
            source_count=result.source_count,
            top_retrieval_score=result.top_retrieval_score,
            retrieval_threshold_applied=result.retrieval_threshold_applied,
        )

        await db.commit()

        # Phase 10: Record RAG Observability Telemetry
        from app.core.metrics import get_metrics_registry
        metrics = get_metrics_registry()
        metrics.observe_retrieval(result.retrieval_latency_ms / 1000.0)
        metrics.observe_embedding(result.embedding_latency_ms / 1000.0)
        metrics.observe_rag_generation(result.generation_latency_ms / 1000.0)

        logger.info(
            "copilot_query_telemetry",
            conversation_id=result.conversation_id,
            top_retrieval_score=result.top_retrieval_score,
            source_count=result.source_count,
            chunk_count=result.chunk_count,
            embedding_latency_ms=result.embedding_latency_ms,
            retrieval_latency_ms=result.retrieval_latency_ms,
            generation_latency_ms=result.generation_latency_ms,
            total_latency_ms=result.total_latency_ms,
            offline_mode=result.offline_mode,
            model_used=result.model_used,
        )

        return CopilotQueryResponse(
            conversation_id=result.conversation_id,
            answer=result.answer,
            sources=api_sources,
            evidence=evidence,
            retrieval_latency_ms=result.retrieval_latency_ms,
            generation_latency_ms=result.generation_latency_ms,
            total_latency_ms=result.total_latency_ms,
            embedding_latency_ms=result.embedding_latency_ms,
            offline_mode=result.offline_mode,
            model_used=result.model_used,
            insufficient_evidence=result.insufficient_evidence,
        )

    except OllamaUnavailableError as e:
        logger.error("copilot_ollama_unavailable", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"OLLAMA_UNAVAILABLE: Ollama server is not reachable. Ensure Ollama is running at the configured URL.",
        )
    except OllamaModelNotFoundError as e:
        logger.error("copilot_model_not_found", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"OLLAMA_MODEL_UNAVAILABLE: {e}",
        )
    except OllamaTimeoutError as e:
        logger.error("copilot_timeout", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"OLLAMA_TIMEOUT: {e}",
        )
    except OllamaGenerationError as e:
        logger.error("copilot_generation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OLLAMA_GENERATION_ERROR: {e}",
        )
    except Exception as exc:
        logger.error("copilot_query_failed", question=request.question[:100], error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Copilot query processing failed due to an internal server error.",
        )
