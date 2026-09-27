"""Documents API — Upload, list, inspect, delete documents."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.api import (
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    DocumentVersionResponse,
    ErrorResponse,
    PaginationParams,
    SuccessResponse,
)

router = APIRouter()


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=201,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    description: str | None = Form(None),
    document_type: str | None = Form(None),
    sensitivity: str = Form("internal"),
    source_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload and process a document."""
    # Implemented in Phase 2
    raise HTTPException(status_code=501, detail="Document upload not yet implemented")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = 1,
    page_size: int = 50,
    processing_status: str | None = None,
    document_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all documents with optional filtering."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Get document details by ID."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/{document_id}", response_model=SuccessResponse)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete a document."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/{document_id}/reindex", response_model=SuccessResponse)
async def reindex_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Re-process and re-index a document."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def get_document_versions(document_id: str, db: AsyncSession = Depends(get_db)):
    """Get version history for a document."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
