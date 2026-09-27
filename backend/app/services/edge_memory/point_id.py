"""
EDGEWISE AI — Deterministic Vector Point ID Strategy

Strategy:
Qdrant requires Point IDs to be either unsigned 64-bit integers or valid UUID strings.
To guarantee deterministic, idempotent indexing across re-index operations and avoid
duplicate points, we derive point IDs using UUIDv5 with a dedicated Edgewise namespace.

Namespace:
    EDGEWISE_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "memory.edgewise.ai")

Deterministic Key:
    "doc:{document_id}:idx:{chunk_index}:hash:{content_hash}"

Guarantees:
1. Re-indexing identical content with the same chunk index produces the EXACT same UUID.
2. Qdrant's upsert_points overwrites the existing point in-place without producing duplicates.
3. Content changes result in a new deterministic UUID, enabling obsolete point removal.
4. Complies strictly with Qdrant Point ID UUID parsing.
"""

from __future__ import annotations

import uuid

# Fixed namespace for Edgewise vector point deterministic UUID generation
EDGEWISE_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "memory.edgewise.ai")


def generate_point_id(
    document_id: str,
    chunk_index: int,
    content_hash: str,
) -> str:
    """
    Generate a deterministic UUID string for a document chunk vector point.
    """
    name = f"doc:{document_id}:idx:{chunk_index}:hash:{content_hash}"
    return str(uuid.uuid5(EDGEWISE_POINT_NAMESPACE, name))


def generate_point_id_from_chunk_id(chunk_id: str) -> str:
    """
    Generate a deterministic UUID string directly from a chunk ID.
    If chunk_id is already a valid UUID string, returns normalized lowercase UUID string.
    Otherwise derives UUIDv5 from chunk_id.
    """
    try:
        parsed = uuid.UUID(chunk_id)
        return str(parsed)
    except (ValueError, AttributeError):
        return str(uuid.uuid5(EDGEWISE_POINT_NAMESPACE, f"chunk:{chunk_id}"))
