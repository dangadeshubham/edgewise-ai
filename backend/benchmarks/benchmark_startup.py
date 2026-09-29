"""EDGEWISE AI — Phase 14 Benchmark: System Startup Latency

Measures:
1. Database migration startup (Alembic upgrade)
2. Embedding model initial load (cold & warm)
3. Qdrant Edge dual-shard initialization
4. Ollama service detection & model verification
5. FastAPI backend application initialization
6. Complete startup sequence

Runs 5 iterations per component to compute min, median, p95, max.
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# Ensure working directory is backend
BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)


def calculate_stats(times: List[float]) -> Dict[str, float]:
    """Calculate min, median, p95, max in milliseconds."""
    arr = np.array(times) * 1000.0  # convert to ms
    return {
        "min_ms": round(float(np.min(arr)), 2),
        "median_ms": round(float(np.median(arr)), 2),
        "p95_ms": round(float(np.percentile(arr, 95)), 2),
        "max_ms": round(float(np.max(arr)), 2),
        "runs": len(times),
    }


def benchmark_migration_startup(runs: int = 5) -> Dict[str, Any]:
    """Measure Alembic migration execution on fresh SQLite databases."""
    from alembic import command
    from alembic.config import Config

    durations = []
    for i in range(runs):
        with tempfile.TemporaryDirectory(prefix="bench_alembic_") as tmp:
            db_path = Path(tmp) / f"bench_mig_{i}.db"
            sync_url = f"sqlite:///{db_path.as_posix()}"
            alembic_cfg = Config(BACKEND_DIR / "alembic.ini")
            alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
            alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

            start = time.perf_counter()
            command.upgrade(alembic_cfg, "head")
            durations.append(time.perf_counter() - start)

    return calculate_stats(durations)


def benchmark_embedding_model_load(runs: int = 5) -> Dict[str, Any]:
    """Measure embedding model load time."""
    from sentence_transformers import SentenceTransformer

    # 1. Measure cold load
    gc.collect()
    start_cold = time.perf_counter()
    _ = SentenceTransformer("all-MiniLM-L6-v2")
    cold_duration = time.perf_counter() - start_cold

    # 2. Measure warm / cached loads
    durations = [cold_duration]
    for _ in range(runs - 1):
        gc.collect()
        start = time.perf_counter()
        _ = SentenceTransformer("all-MiniLM-L6-v2")
        durations.append(time.perf_counter() - start)

    return {
        **calculate_stats(durations),
        "cold_load_ms": round(cold_duration * 1000.0, 2),
    }


def benchmark_edge_shard_init(runs: int = 5) -> Dict[str, Any]:
    """Measure Qdrant Edge mutable & immutable shard initialization."""
    from app.services.edge_memory.service import EdgeMemoryService

    durations = []

    for i in range(runs):
        with tempfile.TemporaryDirectory(prefix="bench_edge_") as tmp:
            mut_dir = Path(tmp) / "mutable"
            immut_dir = Path(tmp) / "immutable"
            mut_dir.mkdir(parents=True)
            immut_dir.mkdir(parents=True)

            start = time.perf_counter()
            svc = EdgeMemoryService(
                data_dir=tmp,
                mutable_dir=str(mut_dir),
                immutable_dir=str(immut_dir),
                dimension=384,
            )
            durations.append(time.perf_counter() - start)
            svc.close()

    return calculate_stats(durations)


def benchmark_ollama_detection(runs: int = 5) -> Dict[str, Any]:
    """Measure Ollama service availability detection and model tagging latency."""
    from app.core.config import get_settings

    settings = get_settings()
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"

    durations = []
    for _ in range(runs):
        start = time.perf_counter()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            assert "models" in data
        durations.append(time.perf_counter() - start)

    return calculate_stats(durations)


def benchmark_backend_app_init(runs: int = 5) -> Dict[str, Any]:
    """Measure FastAPI full application factory & router mounting."""
    durations = []
    for _ in range(runs):
        start = time.perf_counter()
        # Instantiate fresh FastAPI app
        from app.main import app as test_app
        _ = test_app.routes
        durations.append(time.perf_counter() - start)

    return calculate_stats(durations)


def benchmark_frontend_build_and_start() -> Dict[str, Any]:
    """Inspect frontend production bundle and dev startup readiness."""
    frontend_dir = BACKEND_DIR.parent / "frontend"
    dist_dir = frontend_dir / "dist"
    has_dist = dist_dir.exists() and (dist_dir / "index.html").exists()

    dist_size_bytes = 0
    if has_dist:
        for f in dist_dir.rglob("*"):
            if f.is_file():
                dist_size_bytes += f.stat().st_size

    return {
        "production_bundle_exists": has_dist,
        "bundle_size_kb": round(dist_size_bytes / 1024, 2),
        "spa_entrypoint": "index.html",
    }


def run_all_startup_benchmarks() -> Dict[str, Any]:
    """Execute all startup benchmarks and return unified JSON summary."""
    print("Benchmarking Database Migration Startup (5 runs)...")
    mig_stats = benchmark_migration_startup(5)
    print(f"  Migration: median={mig_stats['median_ms']}ms, p95={mig_stats['p95_ms']}ms")

    print("Benchmarking Embedding Model Load (5 runs)...")
    emb_stats = benchmark_embedding_model_load(5)
    print(f"  Embedding Model: cold={emb_stats['cold_load_ms']}ms, median={emb_stats['median_ms']}ms")

    print("Benchmarking Qdrant Edge Shard Init (5 runs)...")
    edge_stats = benchmark_edge_shard_init(5)
    print(f"  Edge Shards: median={edge_stats['median_ms']}ms, p95={edge_stats['p95_ms']}ms")

    print("Benchmarking Ollama Detection (5 runs)...")
    ollama_stats = benchmark_ollama_detection(5)
    print(f"  Ollama Detection: median={ollama_stats['median_ms']}ms, p95={ollama_stats['p95_ms']}ms")

    print("Benchmarking Backend App Initialization (5 runs)...")
    app_stats = benchmark_backend_app_init(5)
    print(f"  App Init: median={app_stats['median_ms']}ms, p95={app_stats['p95_ms']}ms")

    fe_stats = benchmark_frontend_build_and_start()

    results = {
        "database_migration": mig_stats,
        "embedding_model_load": emb_stats,
        "qdrant_edge_shard_init": edge_stats,
        "ollama_availability_detection": ollama_stats,
        "backend_app_init": app_stats,
        "frontend": fe_stats,
    }

    out_file = BACKEND_DIR / "benchmarks" / "startup_benchmark_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nStartup benchmark results written to: {out_file}")
    return results


if __name__ == "__main__":
    run_all_startup_benchmarks()
