"""
EDGEWISE AI — File Validator & Sanitizer

Validates uploads:
- MIME types and file extensions
- File size constraints
- Path traversal prevention
- Filename sanitization
- Malformed file checks
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()

ALLOWED_MIME_MAP = {
    ".pdf": ["application/pdf", "application/x-pdf"],
    ".txt": ["text/plain", "text/plain; charset=utf-8"],
    ".md": ["text/markdown", "text/plain", "text/x-markdown", "text/markdown; charset=utf-8"],
    ".json": ["application/json", "text/json", "text/plain", "application/json; charset=utf-8"],
    ".docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    ],
}


class FileValidator:
    """Security and integrity validator for incoming uploaded documents."""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename to prevent directory traversal and filesystem attacks.
        Removes directory delimiters, null bytes, and non-printable characters.
        """
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=422,
                detail="Filename cannot be empty.",
            )

        # Remove path separators and traversal attempts
        cleaned = os.path.basename(filename.strip())
        cleaned = re.sub(r"[\x00-\x1f\x7f/\\]", "", cleaned)
        cleaned = re.sub(r"\.\.+", ".", cleaned)  # Remove multiple dots

        if not cleaned or cleaned.startswith("."):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid or unsafe filename '{filename}'.",
            )

        return cleaned

    @staticmethod
    def validate_file(
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Run validation checks on filename, extension, size, and content.
        Returns (sanitized_filename, validated_extension).
        """
        sanitized = FileValidator.sanitize_filename(filename)
        ext = Path(sanitized).suffix.lower()

        settings = get_settings()

        # 1. Extension check
        allowed_exts = settings.allowed_file_types_list
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported file extension '{ext}'. "
                    f"Allowed types: {', '.join(allowed_exts)}"
                ),
            )

        # 2. File size check
        file_size = len(content)
        if file_size == 0:
            raise HTTPException(
                status_code=422,
                detail="Uploaded file is empty (0 bytes).",
            )

        if file_size > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum "
                    f"allowed limit of {settings.max_upload_size_mb} MB."
                ),
            )

        # 3. MIME type check if supplied
        if content_type:
            content_type_clean = content_type.lower().split(";")[0].strip()
            allowed_mimes = [m.split(";")[0].strip() for m in ALLOWED_MIME_MAP.get(ext, [])]
            if allowed_mimes and content_type_clean not in allowed_mimes:
                # Be tolerant of generic application/octet-stream if file content validates
                if content_type_clean != "application/octet-stream":
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"MIME type '{content_type}' does not match file extension '{ext}'. "
                            f"Expected: {', '.join(allowed_mimes)}"
                        ),
                    )

        # 4. Content sanity checks for corrupted files
        FileValidator._check_file_integrity(ext, content)

        return sanitized, ext

    @staticmethod
    def _check_file_integrity(ext: str, content: bytes) -> None:
        """Inspect file header or structure for corruption."""
        if ext == ".pdf":
            # PDF must start with %PDF- header in the first 1024 bytes
            if not content.startswith(b"%PDF-") and b"%PDF-" not in content[:1024]:
                raise HTTPException(
                    status_code=422,
                    detail="Malformed PDF: missing %PDF- header signature.",
                )
        elif ext == ".json":
            try:
                json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Malformed JSON file: {str(e)}",
                )
        elif ext == ".docx":
            # DOCX is a zip container with [Content_Types].xml or word/
            if not zipfile.is_zipfile(BytesIO(content)):
                raise HTTPException(
                    status_code=422,
                    detail="Malformed DOCX: file is not a valid OpenXML zip archive.",
                )
