"""
EDGEWISE AI — Embedding Service

Loads and serves local dense embedding models via SentenceTransformers.
Enforces strict fail-fast validation against configured vector dimensions.
"""

from __future__ import annotations

import time
from typing import Optional
import numpy as np
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class EmbeddingDimensionMismatchError(Exception):
    """Raised when generated embedding dimension does not match configured dimension."""
    pass


class EmbeddingModelUnavailableError(Exception):
    """Raised when embedding model cannot be loaded or executed."""
    pass


class EmbeddingService:
    """
    Embedding service for generating dense vector representations of text.
    Uses SentenceTransformers with fail-fast dimension validation at initialization.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        expected_dimension: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self.model_name: str = model_name or settings.embedding_model_name
        self.expected_dimension: int = expected_dimension or settings.edge_vector_dimension
        self._model = None
        self._dimension: int = self.expected_dimension
        self.last_latency_ms: float = 0.0

        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Load the model and immediately validate embedding dimension."""
        log = logger.bind(model_name=self.model_name, expected_dimension=self.expected_dimension)
        log.info("loading_embedding_model")

        try:
            from sentence_transformers import SentenceTransformer

            t0 = time.perf_counter()
            # If the user passed just the short name like 'all-MiniLM-L6-v2', map it if needed
            full_model_name = self.model_name
            if not ("/" in full_model_name or "\\" in full_model_name):
                full_model_name = f"sentence-transformers/{self.model_name}"

            self._model = SentenceTransformer(full_model_name)
            load_time_ms = (time.perf_counter() - t0) * 1000
            log.info("embedding_model_loaded", load_time_ms=round(load_time_ms, 2))

        except Exception as exc:
            log.error("embedding_model_load_failed", error=str(exc))
            raise EmbeddingModelUnavailableError(
                f"Failed to load embedding model '{self.model_name}': {str(exc)}"
            ) from exc

        # Validation probe
        try:
            t0 = time.perf_counter()
            probe_vector = self.embed_text("edgewise validation probe")
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            actual_dim = len(probe_vector)
            self._dimension = actual_dim

            if actual_dim != self.expected_dimension:
                err_msg = (
                    f"Embedding dimension mismatch: model '{self.model_name}' produced "
                    f"{actual_dim} dimensions, but system is configured for {self.expected_dimension}. "
                    f"Refusing to silently pad or truncate."
                )
                log.error("embedding_dimension_mismatch", actual=actual_dim, expected=self.expected_dimension)
                raise EmbeddingDimensionMismatchError(err_msg)

            log.info(
                "embedding_model_validated",
                dimension=actual_dim,
                probe_latency_ms=round(self.last_latency_ms, 2),
            )

        except EmbeddingDimensionMismatchError:
            raise
        except Exception as exc:
            log.error("embedding_model_validation_probe_failed", error=str(exc))
            raise EmbeddingModelUnavailableError(
                f"Embedding validation probe failed for model '{self.model_name}': {str(exc)}"
            ) from exc

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        """
        Generate a normalized dense vector embedding for a single text string.
        """
        if self._model is None:
            raise EmbeddingModelUnavailableError("Embedding model is not loaded.")

        if not text or not text.strip():
            # Generate embedding for whitespace/empty string instead of failing
            text = " "

        t0 = time.perf_counter()
        try:
            vector = self._model.encode(text, normalize_embeddings=True)
            self.last_latency_ms = (time.perf_counter() - t0) * 1000

            if isinstance(vector, np.ndarray):
                return vector.tolist()
            return list(vector)
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                f"Failed to generate embedding: {str(exc)}"
            ) from exc

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """
        Generate normalized dense vector embeddings for a list of texts in batches.
        """
        if self._model is None:
            raise EmbeddingModelUnavailableError("Embedding model is not loaded.")

        if not texts:
            return []

        # Sanitize empty items
        cleaned = [t if t and t.strip() else " " for t in texts]

        t0 = time.perf_counter()
        try:
            vectors = self._model.encode(
                cleaned,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            self.last_latency_ms = (time.perf_counter() - t0) * 1000

            if isinstance(vectors, np.ndarray):
                return vectors.tolist()
            return [v.tolist() if isinstance(v, np.ndarray) else list(v) for v in vectors]
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                f"Failed to generate batch embeddings: {str(exc)}"
            ) from exc

    def is_healthy(self) -> bool:
        """Verify model is loaded and can encode."""
        if self._model is None:
            return False
        try:
            probe = self.embed_text("health")
            return len(probe) == self.expected_dimension
        except Exception:
            return False


# Singleton instance cache
_embedding_service_instance: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Return singleton EmbeddingService."""
    global _embedding_service_instance
    if _embedding_service_instance is None:
        _embedding_service_instance = EmbeddingService()
    return _embedding_service_instance


def reset_embedding_service() -> None:
    """Reset the singleton instance (useful for testing)."""
    global _embedding_service_instance
    _embedding_service_instance = None
