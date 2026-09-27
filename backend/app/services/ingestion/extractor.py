"""
EDGEWISE AI — Text Extractors

Real text extraction for supported document formats:
- PDF (PyMuPDF page-by-page extraction; detects image-only/scanned PDFs)
- DOCX (python-docx paragraph and table extraction)
- Markdown (heading preservation)
- JSON (structured, depth-limited searchable representation)
- TXT (robust encoding detection with safe fallback)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

import pymupdf as fitz
from docx import Document as DocxDocument


@dataclass
class PageContent:
    page_number: int
    text: str


@dataclass
class ExtractedDocument:
    text: str
    pages: list[PageContent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TextExtractionError(Exception):
    """Raised when text extraction fails or yields no extractable text."""
    pass


class DocumentExtractor:
    """Dispatches text extraction according to file extension."""

    @classmethod
    def extract(cls, content: bytes, extension: str, filename: str = "") -> ExtractedDocument:
        ext = extension.lower()
        if ext == ".pdf":
            return cls._extract_pdf(content, filename)
        elif ext == ".docx":
            return cls._extract_docx(content, filename)
        elif ext == ".md":
            return cls._extract_markdown(content, filename)
        elif ext == ".json":
            return cls._extract_json(content, filename)
        elif ext == ".txt":
            return cls._extract_txt(content, filename)
        else:
            raise TextExtractionError(f"Unsupported document format for extraction: '{ext}'")

    @classmethod
    def _extract_pdf(cls, content: bytes, filename: str) -> ExtractedDocument:
        """Extract text from PDF page-by-page using PyMuPDF."""
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise TextExtractionError(f"Failed to parse PDF document: {str(e)}")

        pages: list[PageContent] = []
        full_text_parts: list[str] = []

        total_pages = len(doc)
        for page_idx in range(total_pages):
            page = doc.load_page(page_idx)
            page_text = page.get_text("text") or ""
            page_num = page_idx + 1

            if page_text.strip():
                pages.append(PageContent(page_number=page_num, text=page_text))
                full_text_parts.append(page_text)

        doc.close()

        # Check for image-only or scanned PDFs without text
        if not full_text_parts or not any(p.strip() for p in full_text_parts):
            raise TextExtractionError("Image-only PDF; OCR not available.")

        combined_text = "\n\n".join(full_text_parts)
        return ExtractedDocument(
            text=combined_text,
            pages=pages,
            metadata={"page_count": total_pages, "extractable_pages": len(pages)},
        )

    @classmethod
    def _extract_docx(cls, content: bytes, filename: str) -> ExtractedDocument:
        """Extract paragraphs and table text from DOCX."""
        try:
            doc = DocxDocument(BytesIO(content))
        except Exception as e:
            raise TextExtractionError(f"Failed to parse DOCX document: {str(e)}")

        parts: list[str] = []

        # Extract regular paragraphs
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                parts.append(text)

        # Extract table contents if present
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    parts.append(" | ".join(row_cells))

        if not parts:
            raise TextExtractionError("DOCX document contains no readable text content.")

        combined_text = "\n\n".join(parts)
        return ExtractedDocument(
            text=combined_text,
            pages=[PageContent(page_number=1, text=combined_text)],
            metadata={"paragraph_count": len(doc.paragraphs), "table_count": len(doc.tables)},
        )

    @classmethod
    def _extract_markdown(cls, content: bytes, filename: str) -> ExtractedDocument:
        """Extract Markdown text while preserving heading hierarchy."""
        text = cls._decode_text(content)
        if not text.strip():
            raise TextExtractionError("Markdown document is empty.")

        return ExtractedDocument(
            text=text,
            pages=[PageContent(page_number=1, text=text)],
            metadata={"format": "markdown"},
        )

    @classmethod
    def _extract_json(cls, content: bytes, filename: str) -> ExtractedDocument:
        """Parse JSON and produce structured searchable text representation."""
        try:
            raw_text = cls._decode_text(content)
            data = json.loads(raw_text)
        except Exception as e:
            raise TextExtractionError(f"Failed to parse JSON content: {str(e)}")

        # Flatten JSON to searchable key-value lines with depth and count limits
        lines: list[str] = []

        def flatten(obj: Any, prefix: str = "", depth: int = 0) -> None:
            if depth > 8 or len(lines) >= 1000:
                if len(lines) < 1000:
                    lines.append(f"{prefix}: [nested content truncated]")
                return

            if isinstance(obj, dict):
                for k, v in obj.items():
                    key_str = f"{prefix}.{k}" if prefix else str(k)
                    flatten(v, key_str, depth + 1)
            elif isinstance(obj, list):
                if len(obj) > 50:
                    lines.append(f"{prefix}: list with {len(obj)} items")
                    for i, item in enumerate(obj[:20]):
                        flatten(item, f"{prefix}[{i}]", depth + 1)
                    lines.append(f"{prefix}: ... ({len(obj) - 20} more items)")
                else:
                    for i, item in enumerate(obj):
                        flatten(item, f"{prefix}[{i}]", depth + 1)
            else:
                lines.append(f"{prefix}: {obj}")

        flatten(data)
        combined_text = "\n".join(lines)
        if not combined_text.strip():
            combined_text = raw_text

        return ExtractedDocument(
            text=combined_text,
            pages=[PageContent(page_number=1, text=combined_text)],
            metadata={"format": "json", "line_count": len(lines)},
        )

    @classmethod
    def _extract_txt(cls, content: bytes, filename: str) -> ExtractedDocument:
        """Extract plain text with safe encoding detection/fallback."""
        text = cls._decode_text(content)
        if not text.strip():
            raise TextExtractionError("Text document contains no readable characters.")

        return ExtractedDocument(
            text=text,
            pages=[PageContent(page_number=1, text=text)],
            metadata={"format": "txt"},
        )

    @staticmethod
    def _decode_text(content: bytes) -> str:
        """Safely decode bytes with utf-8 or graceful fallback."""
        for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        # Ultimate fallback with character replacement
        return content.decode("utf-8", errors="replace")
