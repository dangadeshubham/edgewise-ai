"""EDGEWISE AI — Phase 14 Benchmark: Local Search Latency & Qdrant Edge Optimization

Measures:
1. Local Search Retrieval Stages across Increasing Dataset Sizes (100, 500, 1000, 2000 chunks):
   - Query embedding latency
   - Edge vector query latency (dense & hybrid)
   - Metadata filtering latency
   - Result deduplication & merge latency
   - Total end-to-end search latency
   Computes p50, p95, and p99 distributions over 50 search executions per scale.

2. Qdrant Edge Shard Optimization (Phase 14 Section 15):
   - Query latency BEFORE optimization
   - Disk storage size BEFORE optimization
   - Optimization execution time
   - Query latency AFTER optimization
   - Disk storage size AFTER optimization
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import qdrant_edge

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import get_settings
from app.services.edge_memory import generate_point_id
from app.services.edge_memory.service import EdgeMemoryService
from app.services.edge_memory.unified_search import LocalMemorySearch
from app.services.embeddings import get_embedding_service


def compute_percentiles(values: List[float]) -> Dict[str, float]:
    arr = np.array(values)
    return {
        "p50_ms": round(float(np.percentile(arr, 50)), 2),
        "p95_ms": round(float(np.percentile(arr, 95)), 2),
        "p99_ms": round(float(np.percentile(arr, 99)), 2),
        "min_ms": round(float(np.min(arr)), 2),
        "max_ms": round(float(np.max(arr)), 2),
    }


def get_dir_size_bytes(directory: Path) -> int:
    """Return total bytes on disk for a directory."""
    total = 0
    if not directory.exists():
        return 0
    for p in directory.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def benchmark_search_and_optimization(dataset_scales: List[int] = [100, 500, 1000, 2000]) -> Dict[str, Any]:
    embedding_service = get_embedding_service()
    results: Dict[str, Any] = {"dataset_scales": {}, "shard_optimization": {}}

    test_queries = [
        "What is the maximum nominal pressure for Model CP-400 centrifugal pump?",
        "How often should mechanical shaft seals be inspected for glycol cavitation?",
        "What lubricant specification conforms to bearing maintenance?",
        "What are the emergency shutdown protocols for abnormal impeller vibration?",
        "How to verify suction valve alignment deflection with laser gauges?",
        "What telemetry protocol communicates stator temperature and flow rate?",
        "What lockout tagout procedure applies to motor drive electrical terminals?",
        "When should thermal relief bypass lines be purged for scale removal?",
    ]

    # Pre-generate embeddings for standard manual chunks
    sample_texts = [
        f"Section {i}. Centrifugal pump CP-400 specification #{i}: nominal pressure {4.0 + (i%5)*0.8} bar. "
        f"Seal inspection every {400 + (i%4)*50} hours. Bearing lube ISO VG {46 + (i%2)*22}. "
        f"Emergency shutdown EDP-0{1 + i%5} on vibration > 2.8 mm/s RMS."
        for i in range(max(dataset_scales))
    ]
    print(f"Generating vectors for {len(sample_texts)} benchmark points...")
    all_vectors = embedding_service.embed_texts(sample_texts, batch_size=32)

    with tempfile.TemporaryDirectory(prefix="bench_search_") as tmp:
        mut_path = Path(tmp) / "mutable"
        immut_path = Path(tmp) / "immutable"
        edge_svc = EdgeMemoryService(
            data_dir=tmp,
            mutable_dir=str(mut_path),
            immutable_dir=str(immut_path),
            dimension=384,
        )

        for scale in dataset_scales:
            print(f"\nPopulating Qdrant Edge index to {scale} chunks...")
            # Upsert up to scale points
            for i in range(scale):
                pid = generate_point_id(f"doc-scale-{scale}", i, f"hash-{i}")
                edge_svc.upsert_chunk(
                    point_id=pid,
                    dense_vector=all_vectors[i],
                    text=sample_texts[i],
                    payload={
                        "document_id": f"doc-scale-{scale}",
                        "device_id": f"device-{(i%3)+1}",
                        "document_type": "manual" if i % 2 == 0 else "incident",
                        "sensitivity": "internal",
                        "chunk_index": i,
                    },
                    shard_type="mutable",
                )

            # Benchmark 50 query runs
            search_orchestrator = LocalMemorySearch(memory_service=edge_svc, embedding_service=embedding_service)

            t_embed_list = []
            t_query_list = []
            t_filter_list = []
            t_dedup_list = []
            t_total_list = []

            filter_condition = qdrant_edge.Filter(
                must=[qdrant_edge.FieldCondition(key="document_type", match=qdrant_edge.MatchValue(value="manual"))]
            )

            for q_idx in range(50):
                query = test_queries[q_idx % len(test_queries)]

                # Stage 1: Embed query
                t0 = time.perf_counter()
                q_vec = embedding_service.embed_text(query)
                t_embed_ms = (time.perf_counter() - t0) * 1000

                # Stage 2: Dense query without filter
                t0 = time.perf_counter()
                hits = edge_svc.query_points(query_vector=q_vec, limit=10, shard_type="mutable")
                t_query_ms = (time.perf_counter() - t0) * 1000

                # Stage 3: Query with metadata filter
                t0 = time.perf_counter()
                filtered_hits = edge_svc.query_points(
                    query_vector=q_vec, limit=10, filter_obj=filter_condition, shard_type="mutable"
                )
                t_filter_ms = (time.perf_counter() - t0) * 1000

                # Stage 4: Deduplication & sort
                t0 = time.perf_counter()
                seen = {pt.id: pt for pt in hits}
                _ = sorted(seen.values(), key=lambda x: x.score, reverse=True)
                t_dedup_ms = (time.perf_counter() - t0) * 1000

                t_total_ms = t_embed_ms + t_query_ms + t_dedup_ms

                t_embed_list.append(t_embed_ms)
                t_query_list.append(t_query_ms)
                t_filter_list.append(t_filter_ms)
                t_dedup_list.append(t_dedup_ms)
                t_total_list.append(t_total_ms)

            results["dataset_scales"][f"{scale}_chunks"] = {
                "dataset_chunks": scale,
                "query_runs": 50,
                "query_embedding": compute_percentiles(t_embed_list),
                "edge_query_raw": compute_percentiles(t_query_list),
                "edge_query_filtered": compute_percentiles(t_filter_list),
                "result_deduplication": compute_percentiles(t_dedup_list),
                "total_search_latency": compute_percentiles(t_total_list),
            }

            p = results["dataset_scales"][f"{scale}_chunks"]["total_search_latency"]
            print(f"  [{scale} chunks] Total Search: p50={p['p50_ms']}ms, p95={p['p95_ms']}ms, p99={p['p99_ms']}ms")

        # Section 15: Qdrant Edge Shard Optimization Benchmark
        print("\nBenchmarking Qdrant Edge Shard Optimization...")
        size_before_bytes = get_dir_size_bytes(mut_path)

        # Baseline queries before optimization
        pre_latencies = []
        q_vec = embedding_service.embed_text(test_queries[0])
        for _ in range(20):
            t0 = time.perf_counter()
            _ = edge_svc.query_points(query_vector=q_vec, limit=10, shard_type="mutable")
            pre_latencies.append((time.perf_counter() - t0) * 1000)

        # Execute optimization
        t0 = time.perf_counter()
        edge_svc.optimize(shard_type="mutable")
        optimization_duration_ms = (time.perf_counter() - t0) * 1000

        size_after_bytes = get_dir_size_bytes(mut_path)

        # Queries after optimization
        post_latencies = []
        for _ in range(20):
            t0 = time.perf_counter()
            _ = edge_svc.query_points(query_vector=q_vec, limit=10, shard_type="mutable")
            post_latencies.append((time.perf_counter() - t0) * 1000)

        results["shard_optimization"] = {
            "dataset_chunks": max(dataset_scales),
            "size_before_kb": round(size_before_bytes / 1024, 2),
            "size_after_kb": round(size_after_bytes / 1024, 2),
            "storage_delta_kb": round((size_after_bytes - size_before_bytes) / 1024, 2),
            "optimization_duration_ms": round(optimization_duration_ms, 2),
            "query_latency_before": compute_percentiles(pre_latencies),
            "query_latency_after": compute_percentiles(post_latencies),
        }
        print(f"  Optimization took: {results['shard_optimization']['optimization_duration_ms']}ms")
        print(f"  Pre-opt query p50: {results['shard_optimization']['query_latency_before']['p50_ms']}ms")
        print(f"  Post-opt query p50: {results['shard_optimization']['query_latency_after']['p50_ms']}ms")
        print(f"  Disk size before: {results['shard_optimization']['size_before_kb']}KB -> after: {results['shard_optimization']['size_after_kb']}KB")

        edge_svc.close()

    out_file = BACKEND_DIR / "benchmarks" / "search_qdrant_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nSearch benchmark results written to: {out_file}")
    return results


if __name__ == "__main__":
    benchmark_search_and_optimization()
