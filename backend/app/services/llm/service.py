"""
EDGEWISE AI — Ollama LLM Service

Provides a clean interface to Ollama's local LLM API for RAG generation.
All HTTP communication with Ollama is encapsulated here.
Never returns fabricated responses or fake latencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class OllamaUnavailableError(Exception):
    """Raised when Ollama server is not reachable."""
    pass


class OllamaModelNotFoundError(Exception):
    """Raised when the configured model is not available in Ollama."""
    pass


class OllamaGenerationError(Exception):
    """Raised when Ollama fails to generate a response."""
    pass


class OllamaTimeoutError(Exception):
    """Raised when Ollama generation exceeds the configured timeout."""
    pass


@dataclass
class OllamaHealthStatus:
    """Real health check result from Ollama."""
    server_available: bool
    model_available: bool
    model_name: str
    server_latency_ms: float
    available_models: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class GenerationResult:
    """Result of an LLM generation call."""
    text: str
    model_name: str
    generation_latency_ms: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    done: bool = True


class OllamaService:
    """
    Encapsulates all Ollama HTTP interactions.

    Responsibilities:
    - Health check (server + model availability)
    - Text generation with system prompt
    - Timeout handling
    - Latency measurement
    - Error classification
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_timeout

    async def check_health(self) -> OllamaHealthStatus:
        """
        Check Ollama server availability and model presence.
        Returns real measured values only.
        """
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                latency = (time.perf_counter() - t0) * 1000

                if resp.status_code != 200:
                    return OllamaHealthStatus(
                        server_available=False,
                        model_available=False,
                        model_name=self.model,
                        server_latency_ms=round(latency, 2),
                        error=f"Ollama returned HTTP {resp.status_code}",
                    )

                data = resp.json()
                available_models = [m["name"] for m in data.get("models", [])]

                # Check if configured model is available (exact match or prefix match)
                model_found = any(
                    m == self.model or m.startswith(self.model.split(":")[0] + ":")
                    for m in available_models
                )

                return OllamaHealthStatus(
                    server_available=True,
                    model_available=model_found,
                    model_name=self.model,
                    server_latency_ms=round(latency, 2),
                    available_models=available_models,
                    error=None if model_found else f"Model '{self.model}' not found in available models",
                )
        except httpx.ConnectError:
            latency = (time.perf_counter() - t0) * 1000
            return OllamaHealthStatus(
                server_available=False,
                model_available=False,
                model_name=self.model,
                server_latency_ms=round(latency, 2),
                error="OLLAMA_UNAVAILABLE: connection refused",
            )
        except Exception as e:
            latency = (time.perf_counter() - t0) * 1000
            return OllamaHealthStatus(
                server_available=False,
                model_available=False,
                model_name=self.model,
                server_latency_ms=round(latency, 2),
                error=f"OLLAMA_UNAVAILABLE: {type(e).__name__}: {e}",
            )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate a response from the configured Ollama model.
        Raises specific exceptions for different failure modes.
        """
        t0 = time.perf_counter()

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_predict": 1024,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout)) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                latency = (time.perf_counter() - t0) * 1000

                if resp.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{self.model}' not found on Ollama server"
                    )

                if resp.status_code != 200:
                    raise OllamaGenerationError(
                        f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )

                data = resp.json()
                response_text = data.get("response", "").strip()

                return GenerationResult(
                    text=response_text,
                    model_name=self.model,
                    generation_latency_ms=round(latency, 2),
                    prompt_tokens=data.get("prompt_eval_count"),
                    completion_tokens=data.get("eval_count"),
                    total_tokens=(
                        (data.get("prompt_eval_count") or 0) +
                        (data.get("eval_count") or 0)
                    ) or None,
                    done=data.get("done", True),
                )

        except httpx.ConnectError:
            raise OllamaUnavailableError(
                "OLLAMA_UNAVAILABLE: cannot connect to Ollama server"
            )
        except httpx.TimeoutException:
            latency = (time.perf_counter() - t0) * 1000
            raise OllamaTimeoutError(
                f"Ollama generation timed out after {latency:.0f}ms (limit: {self.timeout}s)"
            )
        except (OllamaUnavailableError, OllamaModelNotFoundError,
                OllamaGenerationError, OllamaTimeoutError):
            raise
        except Exception as e:
            raise OllamaGenerationError(
                f"Ollama generation failed: {type(e).__name__}: {e}"
            )


# Module-level singleton
_ollama_service: Optional[OllamaService] = None


def get_ollama_service() -> OllamaService:
    """Get or create the OllamaService singleton."""
    global _ollama_service
    if _ollama_service is None:
        _ollama_service = OllamaService()
    return _ollama_service
