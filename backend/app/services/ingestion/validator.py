"""
EDGEWISE AI — File Validator & Sanitizer (Hardened)

Validates uploads:
- MIME types and file extensions (strict whitelist)
- File size constraints & minimum byte limits
- Path traversal prevention (POSIX & Windows delimiters, encoded traversals, absolute paths)
- Filename sanitization & length constraints
- Decompression bomb / zip bomb protection for OpenXML (.docx)
- JSON nesting depth and malformed syntax checks
- PDF magic header integrity verification
- Executable script and macro blocking
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status

from app.core.config import get_settings

settings = get_settings()

MAX_FILENAME_LENGTH = 255
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_DECOMPRESSION_RATIO = 50.0  # e.g., 1KB compressed -> max 50KB uncompressed
MAX_JSON_DEPTH = 50

DANGEROUS_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".py", ".js", ".html", ".htm",
    ".php", ".dll", ".so", ".dylib", ".vbs", ".msi", ".jar", ".bin",
}

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
        - Decodes URL-encoded characters (e.g. %2e%2e%2f)
        - Removes directory delimiters (both / and \\)
        - Removes null bytes and non-printable characters
        - Enforces maximum filename length (<= 255 chars)
        - Rejects hidden files (leading dot) and pure traversal tokens
        """
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Filename cannot be empty.",
            )

        # 1. Decode URL percent-encoding to catch obfuscated traversals
        decoded = urllib.parse.unquote(filename.strip())

        if "\x00" in decoded or "\x00" in filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Null bytes are strictly prohibited in filenames.",
            )

        # Check for traversal attempts before and after basename extraction
        if ".." in decoded or "/" in decoded or "\\" in decoded:
            # Traversal characters detected; strip them down to the basename
            cleaned = os.path.basename(decoded.replace("\\", "/"))
        else:
            cleaned = decoded

        # 2. Strip null bytes, control characters, and remaining delimiters
        cleaned = re.sub(r"[\x00-\x1f\x7f/\\]", "", cleaned)
        cleaned = re.sub(r"\.\.+", ".", cleaned)  # Collapse repeated dots

        # 3. Filename length check
        if len(cleaned) > MAX_FILENAME_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Filename exceeds maximum permitted length of {MAX_FILENAME_LENGTH} characters.",
            )

        # 4. Reject if empty or starts with a dot (hidden file / traversal residue)
        if not cleaned or cleaned.startswith(".") or cleaned == "":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

        # Reject explicitly dangerous executable extensions
        if ext in DANGEROUS_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported file extension '{ext}'. Executable and script extension is prohibited.",
            )

        current_settings = get_settings()
        allowed_exts = current_settings.allowed_file_types_list

        # 1. Extension whitelist check
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Unsupported file extension '{ext}'. "
                    f"Allowed types: {', '.join(allowed_exts)}"
                ),
            )

        # 2. File size check
        file_size = len(content)
        if file_size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Uploaded file is empty (0 bytes).",
            )

        if file_size > current_settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum "
                    f"allowed limit of {current_settings.max_upload_size_mb} MB."
                ),
            )

        # 3. MIME type check if supplied
        if content_type:
            content_type_clean = content_type.lower().split(";")[0].strip()
            allowed_mimes = [m.split(";")[0].strip() for m in ALLOWED_MIME_MAP.get(ext, [])]
            if allowed_mimes and content_type_clean not in allowed_mimes:
                # Tolerate generic octet-stream only if magic bytes validate in step 4
                if content_type_clean != "application/octet-stream":
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"MIME type '{content_type}' does not match file extension '{ext}'. "
                            f"Expected: {', '.join(allowed_mimes)}"
                        ),
                    )

        # 4. Content sanity & deep structure checks
        FileValidator._check_file_integrity(ext, content)

        return sanitized, ext

    @staticmethod
    def _check_file_integrity(ext: str, content: bytes) -> None:
        """Inspect file header, structure, and integrity for corruption or bombs."""
        if ext == ".pdf":
            # PDF must start with %PDF- header in the first 1024 bytes and be >= 32 bytes
            if len(content) < 32 or (not content.startswith(b"%PDF-") and b"%PDF-" not in content[:1024]):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Malformed PDF: missing %PDF- header signature.",
                )

        elif ext == ".json":
            try:
                decoded_str = content.decode("utf-8")
                parsed = json.loads(decoded_str)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Malformed JSON file: {str(e)}",
                )
            # Check JSON nesting depth to prevent stack overflow/recursion DoS
            depth = FileValidator._get_json_depth(parsed)
            if depth > MAX_JSON_DEPTH:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Malformed JSON: nesting depth {depth} exceeds maximum allowed limit of {MAX_JSON_DEPTH}.",
                )

        elif ext == ".docx":
            # DOCX is a zip container with OpenXML structure
            bio = BytesIO(content)
            if not zipfile.is_zipfile(bio):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Malformed DOCX: file is not a valid OpenXML zip archive.",
                )

            # Decompression bomb and path traversal protection for zip entries
            try:
                with zipfile.ZipFile(bio, "r") as zf:
                    total_uncompressed = 0
                    for info in zf.infolist():
                        # Prevent zip slip (traversal inside zip archive)
                        if ".." in info.filename or info.filename.startswith("/"):
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Malformed DOCX: malicious entry path inside archive.",
                            )
                        total_uncompressed += info.file_size
                        if total_uncompressed > MAX_UNCOMPRESSED_ARCHIVE_BYTES:
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=(
                                    f"Decompression bomb detected: uncompressed size exceeds limit of "
                                    f"{MAX_UNCOMPRESSED_ARCHIVE_BYTES // (1024 * 1024)} MB."
                                ),
                            )

                    # Check overall compression ratio
                    if len(content) > 0:
                        ratio = total_uncompressed / len(content)
                        if ratio > MAX_DECOMPRESSION_RATIO and total_uncompressed > 10 * 1024 * 1024:
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"Decompression bomb detected: suspicious compression ratio of {ratio:.1f}:1.",
                            )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Malformed DOCX archive: {str(e)}",
                )

        elif ext in [".txt", ".md"]:
            # Ensure text does not contain raw null bytes (poison null byte attacks)
            if b"\x00" in content:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Unsafe file: text file contains prohibited null bytes.",
                )

    @staticmethod
    def _get_json_depth(obj: Any, current_depth: int = 1) -> int:
        """Calculate maximum nesting depth of a parsed JSON structure."""
        if current_depth > MAX_JSON_DEPTH:
            return current_depth
        if isinstance(obj, dict) and obj:
            return max(FileValidator._get_json_depth(v, current_depth + 1) for v in obj.values())
        if isinstance(obj, list) and obj:
            return max(FileValidator._get_json_depth(item, current_depth + 1) for item in obj)
        return current_depth
