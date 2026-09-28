"""
EDGEWISE AI — In-Process Lightweight Metrics Engine

Tracks high-resolution operational metrics across ingestion, retrieval, RAG,
synchronization, conflicts, and API requests. Zero external dependencies;
renders Prometheus text format and structured JSON.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict


class MetricsRegistry:
    """Thread-safe registry for Edge operational metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Counters: key -> int
        self._counters: Dict[str, int] = defaultdict(int)
        # Summaries / Histograms: key -> list of float samples (capped to 500)
        self._histograms: Dict[str, list[float]] = defaultdict(list)
        # Gauges: key -> float
        self._gauges: Dict[str, float] = {}

    def inc_request(self, method: str, endpoint: str, status_code: int) -> None:
        key = f'edgewise_requests_total{{method="{method}",endpoint="{endpoint}",status="{status_code}"}}'
        with self._lock:
            self._counters[key] += 1

    def observe_request_duration(self, method: str, endpoint: str, duration_s: float) -> None:
        key = f'edgewise_request_duration_seconds{{method="{method}",endpoint="{endpoint}"}}'
        with self._lock:
            samples = self._histograms[key]
            samples.append(duration_s)
            if len(samples) > 500:
                self._histograms[key] = samples[-500:]

    def inc_error(self, category: str) -> None:
        key = f'edgewise_errors_total{{category="{category}"}}'
        with self._lock:
            self._counters[key] += 1

    def inc_ingestion(self, status: str, chunks_count: int = 0) -> None:
        status_key = f'edgewise_ingestion_total{{status="{status}"}}'
        with self._lock:
            self._counters[status_key] += 1
            if chunks_count > 0:
                self._counters['edgewise_chunks_ingested_total'] += chunks_count

    def observe_embedding(self, duration_s: float) -> None:
        key = 'edgewise_embedding_duration_seconds'
        with self._lock:
            samples = self._histograms[key]
            samples.append(duration_s)
            if len(samples) > 500:
                self._histograms[key] = samples[-500:]

    def observe_retrieval(self, duration_s: float) -> None:
        key = 'edgewise_retrieval_duration_seconds'
        with self._lock:
            samples = self._histograms[key]
            samples.append(duration_s)
            if len(samples) > 500:
                self._histograms[key] = samples[-500:]

    def observe_rag_generation(self, duration_s: float) -> None:
        key = 'edgewise_rag_generation_duration_seconds'
        with self._lock:
            samples = self._histograms[key]
            samples.append(duration_s)
            if len(samples) > 500:
                self._histograms[key] = samples[-500:]

    def inc_sync_run(self, status: str) -> None:
        key = f'edgewise_sync_runs_total{{status="{status}"}}'
        with self._lock:
            self._counters[key] += 1

    def inc_sync_record(self, operation: str, status: str) -> None:
        key = f'edgewise_sync_records_total{{operation="{operation}",status="{status}"}}'
        with self._lock:
            self._counters[key] += 1

    def inc_conflict(self, action: str) -> None:
        key = f'edgewise_conflicts_total{{action="{action}"}}'
        with self._lock:
            self._counters[key] += 1

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        lbl_str = ""
        if labels:
            lbl_str = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
        key = f"{name}{lbl_str}"
        with self._lock:
            self._gauges[key] = value

    def to_prometheus_format(self) -> str:
        """Render metrics in official Prometheus text exposition format (version 0.0.4)."""
        lines: list[str] = [
            "# HELP edgewise_requests_total Total HTTP requests processed.",
            "# TYPE edgewise_requests_total counter",
            "# HELP edgewise_request_duration_seconds HTTP request latency distribution.",
            "# TYPE edgewise_request_duration_seconds summary",
            "# HELP edgewise_errors_total Total application errors categorized.",
            "# TYPE edgewise_errors_total counter",
            "# HELP edgewise_ingestion_total Total documents ingested by status.",
            "# TYPE edgewise_ingestion_total counter",
            "# HELP edgewise_chunks_ingested_total Total text chunks extracted and persisted.",
            "# TYPE edgewise_chunks_ingested_total counter",
            "# HELP edgewise_embedding_duration_seconds Latency of vector embedding operations.",
            "# TYPE edgewise_embedding_duration_seconds summary",
            "# HELP edgewise_retrieval_duration_seconds Latency of vector similarity retrieval.",
            "# TYPE edgewise_retrieval_duration_seconds summary",
            "# HELP edgewise_rag_generation_duration_seconds Latency of local LLM RAG generation.",
            "# TYPE edgewise_rag_generation_duration_seconds summary",
            "# HELP edgewise_sync_runs_total Total cloud synchronization cycles executed.",
            "# TYPE edgewise_sync_runs_total counter",
            "# HELP edgewise_sync_records_total Total records synchronized by operation.",
            "# TYPE edgewise_sync_records_total counter",
            "# HELP edgewise_conflicts_total Total conflict resolution events by action.",
            "# TYPE edgewise_conflicts_total counter",
        ]

        with self._lock:
            for k, v in sorted(self._counters.items()):
                lines.append(f"{k} {v}")

            for k, samples in sorted(self._histograms.items()):
                if samples:
                    count = len(samples)
                    total = sum(samples)
                    lines.append(f"{k}_count {count}")
                    lines.append(f"{k}_sum {total:.6f}")
                    # Estimate p50 and p95
                    sorted_s = sorted(samples)
                    p50 = sorted_s[int(count * 0.5)]
                    p95 = sorted_s[min(int(count * 0.95), count - 1)]
                    prefix = k.split("{")[0]
                    labels = ""
                    if "{" in k:
                        labels = k[k.index("{") + 1 : -1]
                    lbl_50 = f'{labels},quantile="0.5"' if labels else 'quantile="0.5"'
                    lbl_95 = f'{labels},quantile="0.95"' if labels else 'quantile="0.95"'
                    lines.append(f"{prefix}{{{lbl_50}}} {p50:.6f}")
                    lines.append(f"{prefix}{{{lbl_95}}} {p95:.6f}")

            for k, v in sorted(self._gauges.items()):
                lines.append(f"{k} {v}")

        return "\n".join(lines) + "\n"

    def to_json(self) -> Dict[str, Any]:
        """Render JSON telemetry summary."""
        with self._lock:
            hist_summary = {}
            for k, samples in self._histograms.items():
                if samples:
                    hist_summary[k] = {
                        "count": len(samples),
                        "avg_ms": (sum(samples) / len(samples)) * 1000.0,
                        "min_ms": min(samples) * 1000.0,
                        "max_ms": max(samples) * 1000.0,
                    }

            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": hist_summary,
                "timestamp": time.time(),
            }


_GLOBAL_METRICS = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    """Singleton getter for operational metrics registry."""
    return _GLOBAL_METRICS
