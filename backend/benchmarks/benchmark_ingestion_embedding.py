"""EDGEWISE AI — Phase 14 Benchmark: Document Ingestion & Embedding Throughput

Measures:
1. Ingestion Pipeline Stages:
   - Validation & sanitization
   - Text extraction (real text/PDF content)
   - Text cleaning
   - Deterministic chunking
   - Dense embedding generation
   - Qdrant Edge upsert
   - Total pipeline duration
   Scale targets: 10 chunks, 100 chunks, 500 chunks, 1,000 chunks.

2. Embedding Performance & Batch Size Comparison:
   - 1 document, 10 chunks, 100 chunks, 500 chunks, 1,000 chunks
   - Practical batch sizes: 8, 16, 32, 64
   - Evaluates throughput (chunks/second), latency (ms), and RSS memory delta
   - Identifies the optimal batch size for edge hardware
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import psutil
import structlog
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import get_settings
from app.models.database import Base
from app.services.edge_memory import generate_point_id, get_edge_memory_service
from app.services.edge_memory.service import EdgeMemoryService
from app.services.embeddings import get_embedding_service
from app.services.ingestion.chunker import DocumentChunker
from app.services.ingestion.cleaner import TextCleaner
from app.services.ingestion.extractor import DocumentExtractor
from app.services.ingestion.validator import FileValidator

settings = get_settings()


def get_current_rss_mb() -> float:
    """Return current process RSS in MB."""
    return psutil.Process().memory_info().rss / (1024 * 1024)


def generate_benchmark_text(target_chunks: int, avg_words_per_chunk: int = 80) -> str:
    """Generate structured, realistic industrial manual text yielding ~target_chunks."""
    base_paragraphs = [
        "Centrifugal pump Model CP-400 operates within a nominal pressure range of 4.5 to 7.8 bar.",
        "Routine maintenance requires inspecting mechanical shaft seals every 500 operating hours to prevent glycol cavitation.",
        "Bearings should be lubricated with high-temperature lithium-based grease conforming to ISO VG 46 specifications.",
        "In case of abnormal impeller vibration exceeding 2.8 mm/s RMS, the technician must execute emergency shutdown protocol EDP-04.",
        "Suction valve alignment must be verified with laser gauge LG-12 to ensure axial deflection remains below 0.05 mm.",
        "The digital telemetry module reports continuous stator temperature and discharge flow rate via Modbus RTU protocol.",
        "Electrical isolation must strictly follow Lockout/Tagout standard LOTO-2024 prior to servicing motor drive terminals.",
        "Thermal relief bypass lines must be purged biannually to eliminate scale accumulation in the auxiliary heat exchanger.",
    ]

    needed_paragraphs = max(1, int(target_chunks * 2.2))
    repeated_content = []
    for i in range(needed_paragraphs):
        para = base_paragraphs[i % len(base_paragraphs)]
        repeated_content.append(f"Section {i+1}. {para} Additional operational note for unit #{1000 + i%50}.")

    return "\n\n".join(repeated_content)


async def benchmark_ingestion_pipeline(chunk_targets: List[int] = [10, 100, 500, 1000]) -> Dict[str, Any]:
    """Benchmark end-to-end ingestion pipeline across target chunk scales."""
    results = {}
    embedding_service = get_embedding_service()

    for target in chunk_targets:
        raw_text = generate_benchmark_text(target)
        file_bytes = raw_text.encode("utf-8")
        filename = f"benchmark_manual_{target}.txt"

        with tempfile.TemporaryDirectory(prefix=f"bench_ingest_{target}_") as tmp:
            edge_svc = EdgeMemoryService(
                data_dir=tmp,
                mutable_dir=str(Path(tmp) / "mutable"),
                immutable_dir=str(Path(tmp) / "immutable"),
                dimension=384,
            )

            # Stage 1: Validation
            t0 = time.perf_counter()
            sanitized_name, ext = FileValidator.validate_file(filename, file_bytes, "text/plain")
            validation_ms = (time.perf_counter() - t0) * 1000

            # Stage 2: Extraction
            t0 = time.perf_counter()
            extracted = DocumentExtractor.extract(file_bytes, ext, sanitized_name)
            extraction_ms = (time.perf_counter() - t0) * 1000

            # Stage 3: Cleaning
            t0 = time.perf_counter()
            cleaned_text = TextCleaner.clean(extracted.text)
            extracted.text = cleaned_text
            cleaning_ms = (time.perf_counter() - t0) * 1000

            # Stage 4: Chunking
            t0 = time.perf_counter()
            chunker = DocumentChunker()
            chunks = chunker.chunk_document(extracted, f"doc-bench-{target}", f"ver-bench-{target}")
            actual_chunk_count = len(chunks)
            chunking_ms = (time.perf_counter() - t0) * 1000

            # Stage 5: Embedding
            t0 = time.perf_counter()
            chunk_texts = [c.content for c in chunks]
            vectors = embedding_service.embed_texts(chunk_texts, batch_size=32)
            embedding_ms = (time.perf_counter() - t0) * 1000

            # Stage 6: Edge Upsert
            t0 = time.perf_counter()
            for c, vec in zip(chunks, vectors):
                point_id = generate_point_id(f"doc-bench-{target}", c.chunk_index, c.content_hash)
                edge_svc.upsert_chunk(
                    point_id=point_id,
                    dense_vector=vec,
                    text=c.content,
                    payload={"chunk_id": c.chunk_id, "text": c.content},
                    shard_type="mutable",
                )
            edge_upsert_ms = (time.perf_counter() - t0) * 1000

            total_ms = validation_ms + extraction_ms + cleaning_ms + chunking_ms + embedding_ms + edge_upsert_ms

            results[f"{target}_chunks"] = {
                "target_chunks": target,
                "actual_chunks": actual_chunk_count,
                "file_size_bytes": len(file_bytes),
                "validation_ms": round(validation_ms, 2),
                "extraction_ms": round(extraction_ms, 2),
                "cleaning_ms": round(cleaning_ms, 2),
                "chunking_ms": round(chunking_ms, 2),
                "embedding_ms": round(embedding_ms, 2),
                "edge_upsert_ms": round(edge_upsert_ms, 2),
                "total_ingestion_ms": round(total_ms, 2),
                "chunks_per_second": round(actual_chunk_count / (total_ms / 1000.0), 2),
            }
            edge_svc.close()

    return results


def benchmark_embedding_batches(
    chunk_counts: List[int] = [1, 10, 100, 500, 1000],
    batch_sizes: List[int] = [8, 16, 32, 64],
) -> Dict[str, Any]:
    """Compare embedding performance across practical batch sizes."""
    embedding_service = get_embedding_service()
    raw_text = generate_benchmark_text(1000)
    extractor_res = DocumentExtractor.extract(raw_text.encode("utf-8"), ".txt", "bench.txt")
    chunker = DocumentChunker()
    all_chunks = chunker.chunk_document(extractor_res, "doc-emb-bench", "ver-1")
    all_texts = [c.content for c in all_chunks]

    results: Dict[str, Any] = {"scales": {}, "batch_size_comparison": {}}

    # Scale tests with default batch_size=32
    for n in chunk_counts:
        subset = all_texts[:n]
        if not subset:
            subset = ["Single reference calibration document query."]
        gc.collect()
        t0 = time.perf_counter()
        _ = embedding_service.embed_texts(subset, batch_size=32)
        duration_ms = (time.perf_counter() - t0) * 1000

        results["scales"][f"{n}_chunks"] = {
            "chunk_count": len(subset),
            "batch_size": 32,
            "duration_ms": round(duration_ms, 2),
            "chunks_per_sec": round(len(subset) / (duration_ms / 1000.0), 2),
            "avg_ms_per_chunk": round(duration_ms / len(subset), 2),
        }

    # Batch size comparison on 500 chunks
    test_set = all_texts[:500]
    best_bs = 32
    best_rate = 0.0

    for bs in batch_sizes:
        gc.collect()
        rss_before = get_current_rss_mb()
        t0 = time.perf_counter()
        _ = embedding_service.embed_texts(test_set, batch_size=bs)
        duration_ms = (time.perf_counter() - t0) * 1000
        rss_after = get_current_rss_mb()

        rate = len(test_set) / (duration_ms / 1000.0)
        if rate > best_rate:
            best_rate = rate
            best_bs = bs

        results["batch_size_comparison"][f"batch_{bs}"] = {
            "batch_size": bs,
            "chunks_tested": len(test_set),
            "duration_ms": round(duration_ms, 2),
            "chunks_per_sec": round(rate, 2),
            "rss_before_mb": round(rss_before, 2),
            "rss_after_mb": round(rss_after, 2),
            "rss_delta_mb": round(rss_after - rss_before, 2),
        }

    results["optimal_batch_size"] = best_bs
    results["optimal_throughput_chunks_sec"] = round(best_rate, 2)
    return results


async def main():
    print("Running Document Ingestion Pipeline Benchmarks (10, 100, 500, 1000 chunks)...")
    ingest_results = await benchmark_ingestion_pipeline()
    for scale, metrics in ingest_results.items():
        print(f"  [{scale}]: {metrics['actual_chunks']} chunks in {metrics['total_ingestion_ms']}ms ({metrics['chunks_per_second']} chunks/s)")

    print("\nRunning Embedding Batch Size & Throughput Benchmarks...")
    emb_results = benchmark_embedding_batches()
    print(f"  Optimal batch size: {emb_results['optimal_batch_size']} with {emb_results['optimal_throughput_chunks_sec']} chunks/sec")

    combined = {
        "ingestion_pipeline": ingest_results,
        "embedding_benchmarks": emb_results,
    }

    out_file = BACKEND_DIR / "benchmarks" / "ingestion_embedding_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)

    print(f"\nResults successfully written to: {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
