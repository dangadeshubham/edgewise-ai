"""
EDGEWISE AI — Deterministic Document Chunker

Splits cleaned text into deterministic chunks with configurable size and overlap.
Each chunk preserves:
- chunk_id
- document_id
- document_version_id
- chunk_index
- content
- character count
- estimated token count
- page range (start_page, end_page)
- metadata

Configurable via settings.chunk_size and settings.chunk_overlap.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import get_settings
from app.services.ingestion.extractor import ExtractedDocument

settings = get_settings()


@dataclass
class ChunkResult:
    chunk_id: str
    document_id: str
    version_id: Optional[str]
    chunk_index: int
    content: str
    content_hash: str
    char_count: int
    token_estimate: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """Deterministic chunker with boundary-aware sliding window and overlap."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> None:
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be strictly less than "
                f"chunk_size ({self.chunk_size})"
            )

    def chunk_document(
        self,
        extracted: ExtractedDocument,
        document_id: str,
        version_id: Optional[str] = None,
    ) -> list[ChunkResult]:
        """
        Chunk an extracted document while preserving page references and metadata.
        """
        if not extracted.text.strip():
            return []

        # If page information is available, chunk page-by-page to keep page ranges accurate
        if extracted.pages and len(extracted.pages) > 1:
            return self._chunk_paged_document(extracted, document_id, version_id)

        # Single page / flat document chunking
        return self._chunk_flat_text(
            extracted.text,
            document_id,
            version_id,
            page_start=1 if extracted.pages else None,
            page_end=1 if extracted.pages else None,
        )

    def _chunk_paged_document(
        self,
        extracted: ExtractedDocument,
        document_id: str,
        version_id: Optional[str],
    ) -> list[ChunkResult]:
        """Chunk multi-page document tracking page boundaries."""
        chunks: list[ChunkResult] = []
        chunk_index = 0

        for page in extracted.pages:
            page_text = page.text.strip()
            if not page_text:
                continue

            page_chunks = self._chunk_flat_text(
                page_text,
                document_id,
                version_id,
                page_start=page.page_number,
                page_end=page.page_number,
                start_index=chunk_index,
            )
            chunks.extend(page_chunks)
            chunk_index += len(page_chunks)

        return chunks

    def _chunk_flat_text(
        self,
        text: str,
        document_id: str,
        version_id: Optional[str],
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        start_index: int = 0,
    ) -> list[ChunkResult]:
        """Sliding-window deterministic text chunking with natural boundary breaking."""
        text = text.strip()
        if not text:
            return []

        # Short text fits in a single chunk
        if len(text) <= self.chunk_size:
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            token_count = max(1, len(text) // 4)
            return [
                ChunkResult(
                    chunk_id=str(uuid.uuid4()),
                    document_id=document_id,
                    version_id=version_id,
                    chunk_index=start_index,
                    content=text,
                    content_hash=content_hash,
                    char_count=len(text),
                    token_estimate=token_count,
                    page_start=page_start,
                    page_end=page_end,
                    metadata={
                        "chunk_size": self.chunk_size,
                        "chunk_overlap": self.chunk_overlap,
                        "page_start": page_start,
                        "page_end": page_end,
                    },
                )
            ]

        results: list[ChunkResult] = []
        pos = 0
        text_len = len(text)
        current_index = start_index

        while pos < text_len:
            end_pos = min(pos + self.chunk_size, text_len)

            # Try to break on paragraph or sentence boundary if not at end of text
            if end_pos < text_len:
                boundary = self._find_natural_break(text, pos, end_pos)
                if boundary > pos:
                    end_pos = boundary

            chunk_text = text[pos:end_pos].strip()
            if chunk_text:
                content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                token_count = max(1, len(chunk_text) // 4)
                results.append(
                    ChunkResult(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        version_id=version_id,
                        chunk_index=current_index,
                        content=chunk_text,
                        content_hash=content_hash,
                        char_count=len(chunk_text),
                        token_estimate=token_count,
                        page_start=page_start,
                        page_end=page_end,
                        metadata={
                            "chunk_size": self.chunk_size,
                            "chunk_overlap": self.chunk_overlap,
                            "page_start": page_start,
                            "page_end": page_end,
                        },
                    )
                )
                current_index += 1

            if end_pos >= text_len:
                break

            # Slide window forward by (chunk_size - chunk_overlap)
            step = max(1, (end_pos - pos) - self.chunk_overlap)
            pos += step

        return results

    @staticmethod
    def _find_natural_break(text: str, start: int, target_end: int) -> int:
        """Locate closest paragraph, sentence, or word boundary before target_end."""
        window = text[start:target_end]

        # 1. Paragraph boundary (\n\n)
        last_para = window.rfind("\n\n")
        if last_para != -1 and last_para > len(window) // 2:
            return start + last_para + 2

        # 2. Line boundary (\n)
        last_line = window.rfind("\n")
        if last_line != -1 and last_line > len(window) // 2:
            return start + last_line + 1

        # 3. Sentence boundary (". ", "? ", "! ")
        for punct in [". ", "? ", "! "]:
            last_punct = window.rfind(punct)
            if last_punct != -1 and last_punct > len(window) // 2:
                return start + last_punct + 2

        # 4. Word boundary (" ")
        last_space = window.rfind(" ")
        if last_space != -1 and last_space > len(window) // 2:
            return start + last_space + 1

        return target_end
