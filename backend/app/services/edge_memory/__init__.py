"""Edge Memory Service package."""

from app.services.edge_memory.service import (
    EdgeMemoryError,
    EdgeMemoryService,
    ShardCorruptError,
    ShardLoadError,
    VectorDimensionError,
    get_edge_memory_service,
    reset_edge_memory_service,
)
from app.services.edge_memory.point_id import (
    generate_point_id,
    generate_point_id_from_chunk_id,
)
from app.services.edge_memory.filters import build_payload_filter
from app.services.edge_memory.unified_search import (
    LocalMemorySearch,
    UnifiedSearchResult,
)
from app.services.edge_memory.cleanup import (
    VectorCleanupService,
    CleanupReport,
)

__all__ = [
    "EdgeMemoryService",
    "EdgeMemoryError",
    "ShardCorruptError",
    "ShardLoadError",
    "VectorDimensionError",
    "get_edge_memory_service",
    "reset_edge_memory_service",
    "generate_point_id",
    "generate_point_id_from_chunk_id",
    "build_payload_filter",
    "LocalMemorySearch",
    "UnifiedSearchResult",
    "VectorCleanupService",
    "CleanupReport",
]
