"""
EDGEWISE AI — Documents API

Real document upload, processing, inspection, soft-delete, reindexing, and version history.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database import Document
from app.repositories.document import DocumentRepository
from app.schemas.api import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    DocumentVersionResponse,
    ErrorResponse,
    SuccessResponse,
)
from app.services.ingestion.service import IngestionService

router = APIRouter()


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": DocumentUploadResponse, "description": "Duplicate document detected"},
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def upload_document(
    response: Response,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    sensitivity: str = Form("internal"),
    source_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload and ingest a document.
    Validates file, checks content hash deduplication, extracts text,
    cleans, chunks, and creates versions and chunks in SQLite.
    """
    content = await file.read()
    service = IngestionService(db)
    result = await service.ingest_document(
        filename=file.filename or "upload.bin",
        content=content,
        content_type=file.content_type,
        title=title,
        description=description,
        document_type=document_type,
        sensitivity=sensitivity,
        source_id=source_id,
    )

    if result.is_duplicate:
        response.status_code = status.HTTP_200_OK

    return result


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 50,
    processing_status: Optional[str] = None,
    document_type: Optional[str] = None,
    source_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents with pagination and status/type filtering."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 50

    skip = (page - 1) * page_size
    repo = DocumentRepository(db)

    filters = [Document.deleted_at.is_(None)]
    if processing_status:
        filters.append(Document.processing_status == processing_status)
    if document_type:
        filters.append(Document.document_type == document_type)
    if source_id:
        filters.append(Document.source_id == source_id)

    total = await repo.count(filters)
    docs = await repo.list(
        skip=skip,
        limit=page_size,
        filters=filters,
        order_by=Document.created_at.desc(),
    )
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1

    return DocumentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[DocumentResponse.model_validate(d) for d in docs],
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Get details of a specific document by its UUID."""
    repo = DocumentRepository(db)
    doc = await repo.get_by_id(document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' was not found.",
        )
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", response_model=SuccessResponse)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Soft-delete a document and preserve audit trail."""
    service = IngestionService(db)
    await service.delete_document(document_id)
    return SuccessResponse(
        message="Document soft-deleted successfully.",
        data={"id": document_id},
    )


@router.post("/{document_id}/reindex", response_model=SuccessResponse)
async def reindex_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    """Re-extract and re-chunk an existing document from its stored file on disk."""
    service = IngestionService(db)
    doc = await service.reindex_document(document_id)
    return SuccessResponse(
        message="Document reindexed successfully.",
        data={
            "id": doc.id,
            "chunk_count": doc.chunk_count,
            "total_tokens": doc.total_tokens,
        },
    )


@router.get("/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def get_document_versions(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentVersionResponse]:
    """Get complete version history for a document."""
    service = IngestionService(db)
    versions = await service.get_versions(document_id)
    return [DocumentVersionResponse.model_validate(v) for v in versions]
