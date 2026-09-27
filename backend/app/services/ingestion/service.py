"""
EDGEWISE AI — Ingestion Service

Orchestrates the complete document ingestion pipeline:
1. File validation & sanitization
2. SHA-256 Content Hashing & Deduplication Check
3. Secure Server-Side File Storage
4. Audit Trail Event Creation
5. Format-Specific Text Extraction
6. Deterministic Text Cleaning
7. Configurable Chunking
8. Document Version Creation
9. Chunk Persistence in SQLite
10. Real Processing Status Tracking
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.database import Document, DocumentChunk, DocumentVersion
from app.repositories.audit import AuditRepository
from app.repositories.document import DocumentRepository
from app.schemas.api import DocumentUploadResponse
from app.services.ingestion.chunker import DocumentChunker
from app.services.ingestion.cleaner import TextCleaner
from app.services.ingestion.extractor import DocumentExtractor, TextExtractionError
from app.services.ingestion.validator import FileValidator
from app.services.embeddings import get_embedding_service
from app.services.edge_memory import (
    generate_point_id,
    get_edge_memory_service,
)

settings = get_settings()
log = structlog.get_logger("edgewise.ingestion")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IngestionService:
    """Manages document lifecycle from upload to chunk persistence and auditing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.audit_repo = AuditRepository(session)

    async def ingest_document(
        self,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        document_type: Optional[str] = None,
        sensitivity: str = "internal",
        source_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> DocumentUploadResponse:
        """
        Execute full document ingestion pipeline.
        Returns DocumentUploadResponse with real state.
        """
        # 1. Validation & Sanitization
        sanitized_filename, ext = FileValidator.validate_file(filename, content, content_type)

        # 2. Content Hashing (SHA-256)
        content_hash = hashlib.sha256(content).hexdigest()
        file_size = len(content)

        # 3. Deduplication Check
        existing_doc = await self.doc_repo.get_by_content_hash(content_hash)
        if existing_doc is not None:
            await self.audit_repo.log_event(
                event_type="duplicate_detected",
                description=f"Duplicate document upload detected: identical content to '{existing_doc.id}'.",
                entity_type="document",
                entity_id=existing_doc.id,
                details={
                    "filename": sanitized_filename,
                    "existing_filename": existing_doc.original_filename,
                    "content_hash": content_hash,
                },
                severity="info",
                request_id=request_id,
                device_id=settings.device_id,
            )
            await self.session.commit()
            return DocumentUploadResponse(
                id=existing_doc.id,
                filename=existing_doc.original_filename,
                mime_type=existing_doc.mime_type,
                file_size=existing_doc.file_size,
                content_hash=existing_doc.content_hash,
                processing_status="duplicate",
                message=f"Duplicate document detected: content matches existing document '{existing_doc.id}'.",
                is_duplicate=True,
                version=existing_doc.version,
            )

        # 4. Secure File Storage on Disk
        document_id = str(uuid.uuid4())
        upload_dir = Path(settings.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)

        stored_filename = f"{document_id}_{sanitized_filename}"
        disk_path = upload_dir / stored_filename
        with open(disk_path, "wb") as f:
            f.write(content)

        # 5. Persist Document Record (Status: processing)
        now = utcnow()
        effective_mime = content_type or f"application/{ext.replace('.', '')}"
        doc = Document(
            id=document_id,
            device_id=settings.device_id,
            source_id=source_id,
            filename=stored_filename,
            original_filename=sanitized_filename,
            mime_type=effective_mime,
            file_size=file_size,
            content_hash=content_hash,
            file_path=str(disk_path),
            title=title or sanitized_filename,
            description=description,
            document_type=document_type or "manual",
            processing_status="processing",
            processing_error=None,
            sensitivity=sensitivity,
            sync_status="pending",
            version=1,
            revision=1,
            origin_device=settings.device_id,
            chunk_count=0,
            total_tokens=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(doc)

        # Audit events for upload and processing start
        await self.audit_repo.log_event(
            event_type="document_uploaded",
            description=f"Document '{sanitized_filename}' ({file_size} bytes) uploaded.",
            entity_type="document",
            entity_id=document_id,
            details={"filename": sanitized_filename, "size": file_size, "hash": content_hash},
            severity="info",
            request_id=request_id,
            device_id=settings.device_id,
        )
        await self.audit_repo.log_event(
            event_type="processing_started",
            description=f"Started document processing for '{sanitized_filename}'.",
            entity_type="document",
            entity_id=document_id,
            severity="info",
            request_id=request_id,
            device_id=settings.device_id,
        )
        await self.session.flush()

        # 6. Extraction, Cleaning, and Chunking
        try:
            # Text Extraction
            extracted = DocumentExtractor.extract(content, ext, sanitized_filename)

            # Text Cleaning
            cleaned_text = TextCleaner.clean(extracted.text)
            extracted.text = cleaned_text
            for p in extracted.pages:
                p.text = TextCleaner.clean(p.text)

            # Create Initial Document Version
            version_id = str(uuid.uuid4())
            doc_version = DocumentVersion(
                id=version_id,
                document_id=doc.id,
                version=1,
                content_hash=content_hash,
                file_size=file_size,
                change_summary="Initial ingestion",
                created_by_device=settings.device_id,
                created_at=now,
            )
            self.session.add(doc_version)

            # Chunking
            chunker = DocumentChunker()
            chunks = chunker.chunk_document(extracted, document_id, version_id)

            # Generate Embeddings & Upsert to Edge Mutable Shard
            embedding_service = get_embedding_service()
            edge_service = get_edge_memory_service()
            chunk_texts = [c.content for c in chunks]
            vectors = embedding_service.embed_texts(chunk_texts, batch_size=settings.edge_batch_size) if chunk_texts else []

            # Persist Chunks in SQLite & Edge Memory
            for c, vec in zip(chunks, vectors):
                point_id = generate_point_id(doc.id, c.chunk_index, c.content_hash)
                payload = {
                    "document_id": doc.id,
                    "document_version_id": version_id,
                    "chunk_id": c.chunk_id,
                    "source_id": doc.source_id,
                    "device_id": doc.device_id,
                    "title": doc.title or doc.original_filename,
                    "filename": doc.original_filename,
                    "page_start": c.metadata.get("page_start"),
                    "page_end": c.metadata.get("page_end"),
                    "document_type": doc.document_type,
                    "created_at": now.isoformat(),
                    "content_hash": c.content_hash,
                    "sensitivity": doc.sensitivity,
                }
                edge_service.upsert_chunk(
                    point_id=point_id,
                    dense_vector=vec,
                    text=c.content,
                    payload=payload,
                    shard_type="mutable",
                )

                chunk_record = DocumentChunk(
                    id=c.chunk_id,
                    document_id=doc.id,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    content_hash=c.content_hash,
                    token_count=c.token_estimate,
                    is_embedded=True,
                    vector_point_id=point_id,
                    metadata_json=json.dumps(c.metadata),
                    created_at=now,
                )
                self.session.add(chunk_record)

            if chunks:
                edge_service.flush("mutable")

            # 7. Complete Processing
            doc.chunk_count = len(chunks)
            doc.total_tokens = sum(c.token_estimate for c in chunks)
            doc.processing_status = "completed"
            doc.processing_error = None
            doc.indexed_at = utcnow()
            doc.updated_at = utcnow()

            await self.audit_repo.log_event(
                event_type="processing_completed",
                description=f"Document '{doc.id}' successfully processed into {len(chunks)} chunks.",
                entity_type="document",
                entity_id=doc.id,
                details={"chunk_count": len(chunks), "total_tokens": doc.total_tokens},
                severity="info",
                request_id=request_id,
                device_id=settings.device_id,
            )

            await self.session.commit()
            await log.ainfo(
                "document_ingested",
                document_id=doc.id,
                chunks=doc.chunk_count,
                tokens=doc.total_tokens,
            )

            return DocumentUploadResponse(
                id=doc.id,
                filename=doc.original_filename,
                mime_type=doc.mime_type,
                file_size=doc.file_size,
                content_hash=doc.content_hash,
                processing_status="completed",
                message="Document uploaded and processed successfully.",
                is_duplicate=False,
                version=1,
            )

        except TextExtractionError as ee:
            safe_error = str(ee)
            doc.processing_status = "failed"
            doc.processing_error = safe_error
            doc.updated_at = utcnow()

            await self.audit_repo.log_event(
                event_type="processing_failed",
                description=f"Document extraction failed: {safe_error}",
                entity_type="document",
                entity_id=doc.id,
                details={"error": safe_error},
                severity="error",
                request_id=request_id,
                device_id=settings.device_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=422,
                detail=f"Document processing failed: {safe_error}",
            )

        except Exception as exc:
            safe_error = f"Internal processing error: {type(exc).__name__}"
            await log.aerror("document_processing_exception", exc_info=True, document_id=doc.id)
            doc.processing_status = "failed"
            doc.processing_error = safe_error
            doc.updated_at = utcnow()

            await self.audit_repo.log_event(
                event_type="processing_failed",
                description=f"Document processing encountered error: {safe_error}",
                entity_type="document",
                entity_id=doc.id,
                details={"error_type": type(exc).__name__},
                severity="error",
                request_id=request_id,
                device_id=settings.device_id,
            )
            await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document processing failed due to an internal error.",
            )

    async def reindex_document(
        self,
        document_id: str,
        request_id: Optional[str] = None,
    ) -> Document:
        """
        Re-extract and re-chunk an existing document from its stored file on disk.
        """
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found.",
            )

        file_path = Path(doc.file_path)
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stored file for document '{document_id}' is missing from storage.",
            )

        with open(file_path, "rb") as f:
            content = f.read()

        ext = file_path.suffix.lower()

        # Track existing vector point IDs to remove obsolete points
        existing_chunks = (
            await self.session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        old_point_ids = [ch.vector_point_id for ch in existing_chunks if ch.vector_point_id]

        # Delete existing chunks from SQLite
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )

        doc.processing_status = "processing"
        doc.processing_error = None
        await self.session.flush()

        try:
            extracted = DocumentExtractor.extract(content, ext, doc.original_filename)
            cleaned_text = TextCleaner.clean(extracted.text)
            extracted.text = cleaned_text
            for p in extracted.pages:
                p.text = TextCleaner.clean(p.text)

            chunker = DocumentChunker()
            chunks = chunker.chunk_document(extracted, document_id)

            embedding_service = get_embedding_service()
            edge_service = get_edge_memory_service()
            chunk_texts = [c.content for c in chunks]
            vectors = embedding_service.embed_texts(chunk_texts, batch_size=settings.edge_batch_size) if chunk_texts else []

            now = utcnow()
            new_point_ids: set[str] = set()

            for c, vec in zip(chunks, vectors):
                point_id = generate_point_id(doc.id, c.chunk_index, c.content_hash)
                new_point_ids.add(point_id)
                payload = {
                    "document_id": doc.id,
                    "document_version_id": None,
                    "chunk_id": c.chunk_id,
                    "source_id": doc.source_id,
                    "device_id": doc.device_id,
                    "title": doc.title or doc.original_filename,
                    "filename": doc.original_filename,
                    "page_start": c.metadata.get("page_start"),
                    "page_end": c.metadata.get("page_end"),
                    "document_type": doc.document_type,
                    "created_at": now.isoformat(),
                    "content_hash": c.content_hash,
                    "sensitivity": doc.sensitivity,
                }
                edge_service.upsert_chunk(
                    point_id=point_id,
                    dense_vector=vec,
                    text=c.content,
                    payload=payload,
                    shard_type="mutable",
                )

                chunk_record = DocumentChunk(
                    id=c.chunk_id,
                    document_id=doc.id,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    content_hash=c.content_hash,
                    token_count=c.token_estimate,
                    is_embedded=True,
                    vector_point_id=point_id,
                    metadata_json=json.dumps(c.metadata),
                    created_at=now,
                )
                self.session.add(chunk_record)

            # Remove obsolete points from Edge so no orphans remain
            obsolete_point_ids = [pid for pid in old_point_ids if pid not in new_point_ids]
            if obsolete_point_ids:
                edge_service.delete_points(obsolete_point_ids, shard_type="mutable")

            if chunks or obsolete_point_ids:
                edge_service.flush("mutable")

            doc.chunk_count = len(chunks)
            doc.total_tokens = sum(c.token_estimate for c in chunks)
            doc.processing_status = "completed"
            doc.indexed_at = now
            doc.updated_at = now

            await self.audit_repo.log_event(
                event_type="document_reindexed",
                description=f"Reindexed document '{document_id}': generated {len(chunks)} chunks.",
                entity_type="document",
                entity_id=document_id,
                details={"chunk_count": len(chunks), "total_tokens": doc.total_tokens},
                severity="info",
                request_id=request_id,
                device_id=settings.device_id,
            )

            await self.session.commit()
            return doc

        except Exception as exc:
            doc.processing_status = "failed"
            doc.processing_error = str(exc)
            doc.updated_at = utcnow()
            await self.session.commit()
            raise HTTPException(
                status_code=422,
                detail=f"Reindexing failed: {str(exc)}",
            )

    async def update_document_version(
        self,
        document_id: str,
        new_content: bytes,
        change_summary: str = "Updated content",
        request_id: Optional[str] = None,
    ) -> DocumentVersion:
        """
        Create a new DocumentVersion when content changes, retaining old versions.
        """
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found.",
            )

        new_hash = hashlib.sha256(new_content).hexdigest()
        new_size = len(new_content)
        new_version_num = doc.version + 1

        # Write new version to disk
        upload_dir = Path(settings.upload_dir)
        versioned_filename = f"{document_id}_v{new_version_num}_{doc.original_filename}"
        new_path = upload_dir / versioned_filename
        with open(new_path, "wb") as f:
            f.write(new_content)

        # Create new version record
        now = utcnow()
        version_record = DocumentVersion(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            version=new_version_num,
            content_hash=new_hash,
            file_size=new_size,
            change_summary=change_summary,
            created_by_device=settings.device_id,
            created_at=now,
        )
        self.session.add(version_record)

        # Update document record
        doc.version = new_version_num
        doc.revision = doc.revision + 1
        doc.content_hash = new_hash
        doc.file_size = new_size
        doc.filename = versioned_filename
        doc.file_path = str(new_path)
        doc.updated_at = now

        # Re-extract and re-chunk with new content
        ext = Path(doc.original_filename).suffix.lower()
        extracted = DocumentExtractor.extract(new_content, ext, doc.original_filename)
        cleaned_text = TextCleaner.clean(extracted.text)
        extracted.text = cleaned_text
        for p in extracted.pages:
            p.text = TextCleaner.clean(p.text)

        # Track existing vector point IDs to remove obsolete points
        existing_chunks = (
            await self.session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        old_point_ids = [ch.vector_point_id for ch in existing_chunks if ch.vector_point_id]

        # Delete old chunks and add new chunks
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        chunker = DocumentChunker()
        chunks = chunker.chunk_document(extracted, document_id, version_record.id)

        embedding_service = get_embedding_service()
        edge_service = get_edge_memory_service()
        chunk_texts = [c.content for c in chunks]
        vectors = embedding_service.embed_texts(chunk_texts, batch_size=settings.edge_batch_size) if chunk_texts else []

        new_point_ids: set[str] = set()

        for c, vec in zip(chunks, vectors):
            point_id = generate_point_id(doc.id, c.chunk_index, c.content_hash)
            new_point_ids.add(point_id)
            payload = {
                "document_id": doc.id,
                "document_version_id": version_record.id,
                "chunk_id": c.chunk_id,
                "source_id": doc.source_id,
                "device_id": doc.device_id,
                "title": doc.title or doc.original_filename,
                "filename": doc.original_filename,
                "page_start": c.metadata.get("page_start"),
                "page_end": c.metadata.get("page_end"),
                "document_type": doc.document_type,
                "created_at": now.isoformat(),
                "content_hash": c.content_hash,
                "sensitivity": doc.sensitivity,
            }
            edge_service.upsert_chunk(
                point_id=point_id,
                dense_vector=vec,
                text=c.content,
                payload=payload,
                shard_type="mutable",
            )

            chunk_record = DocumentChunk(
                id=c.chunk_id,
                document_id=doc.id,
                chunk_index=c.chunk_index,
                content=c.content,
                content_hash=c.content_hash,
                token_count=c.token_estimate,
                is_embedded=True,
                vector_point_id=point_id,
                metadata_json=json.dumps(c.metadata),
                created_at=now,
            )
            self.session.add(chunk_record)

        # Remove obsolete points from Edge
        obsolete_point_ids = [pid for pid in old_point_ids if pid not in new_point_ids]
        if obsolete_point_ids:
            edge_service.delete_points(obsolete_point_ids, shard_type="mutable")

        if chunks or obsolete_point_ids:
            edge_service.flush("mutable")

        doc.chunk_count = len(chunks)
        doc.total_tokens = sum(c.token_estimate for c in chunks)
        doc.processing_status = "completed"

        await self.audit_repo.log_event(
            event_type="document_version_created",
            description=f"Document '{document_id}' upgraded to version {new_version_num}.",
            entity_type="document",
            entity_id=document_id,
            details={"version": new_version_num, "content_hash": new_hash},
            severity="info",
            request_id=request_id,
            device_id=settings.device_id,
        )

        await self.session.commit()
        return version_record

    async def delete_document(
        self,
        document_id: str,
        request_id: Optional[str] = None,
    ) -> None:
        """Soft-delete a document and audit the deletion, removing vectors from Edge."""
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found.",
            )

        # Remove vectors from Edge mutable shard so deleted content is not searchable
        existing_chunks = (
            await self.session.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        point_ids = [ch.vector_point_id for ch in existing_chunks if ch.vector_point_id]
        if point_ids:
            edge_service = get_edge_memory_service()
            edge_service.delete_points(point_ids, shard_type="mutable")
            edge_service.flush("mutable")

        doc.deleted_at = utcnow()
        doc.updated_at = utcnow()

        await self.audit_repo.log_event(
            event_type="document_deleted",
            description=f"Document '{document_id}' ('{doc.original_filename}') soft-deleted.",
            entity_type="document",
            entity_id=document_id,
            details={"original_filename": doc.original_filename, "vectors_removed": len(point_ids)},
            severity="warning",
            request_id=request_id,
            device_id=settings.device_id,
        )
        await self.session.commit()

    async def get_versions(self, document_id: str) -> Sequence[DocumentVersion]:
        """Fetch all versions for a document."""
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document '{document_id}' not found.",
            )

        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.asc())
        )
        return result.scalars().all()
