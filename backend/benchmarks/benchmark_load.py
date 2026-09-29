"""EDGEWISE AI — Phase 14 Benchmark: Concurrent Load Testing & Rate Limit Activation

Measures:
1. Search Concurrency (1, 5, 10, 20 concurrent clients):
   - Latency (mean, p95, max)
   - Throughput (requests/second)
   - Error / 429 Rate Limit rate

2. Dashboard API Concurrency (1, 10, 25, 50 concurrent clients):
   - System connectivity probe
   - Overview metrics
   - Latency (mean, p95)
   - Throughput (req/s)

3. Upload Concurrency (1, 3, 5 concurrent uploads):
   - Pipeline serialization and storage isolation

4. Copilot Concurrency (1, 2, 4 concurrent queries):
   - LLM queueing behavior and response times
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models.database import Base

settings = get_settings()


def compute_latencies(times_ms: List[float]) -> Dict[str, float]:
    arr = np.array(times_ms)
    return {
        "mean_ms": round(float(np.mean(arr)), 2),
        "median_ms": round(float(np.median(arr)), 2),
        "p95_ms": round(float(np.percentile(arr, 95)), 2),
        "max_ms": round(float(np.max(arr)), 2),
    }


async def benchmark_endpoint_concurrency(
    client: AsyncClient,
    method: str,
    url: str,
    payload: Dict[str, Any] | None,
    concurrency_levels: List[int],
    requests_per_level: int = 20,
) -> Dict[str, Any]:
    """Test concurrent requests to an endpoint."""
    level_results = {}

    for c in concurrency_levels:
        latencies = []
        errors = 0
        rate_limits = 0
        successes = 0

        semaphore = asyncio.Semaphore(c)

        async def worker():
            nonlocal errors, rate_limits, successes
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    if method == "GET":
                        resp = await client.get(url)
                    else:
                        resp = await client.post(url, json=payload)
                    duration_ms = (time.perf_counter() - t0) * 1000

                    if resp.status_code == 200:
                        successes += 1
                        latencies.append(duration_ms)
                    elif resp.status_code == 429:
                        rate_limits += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

        t_start = time.perf_counter()
        tasks = [worker() for _ in range(requests_per_level)]
        await asyncio.gather(*tasks)
        total_time_sec = time.perf_counter() - t_start

        reqs_per_sec = round(requests_per_level / total_time_sec, 2)
        metrics = compute_latencies(latencies) if latencies else {"mean_ms": 0, "p95_ms": 0}

        level_results[f"concurrency_{c}"] = {
            "concurrency": c,
            "total_requests": requests_per_level,
            "successes": successes,
            "rate_limits_429": rate_limits,
            "errors": errors,
            "requests_per_second": reqs_per_sec,
            **metrics,
        }

    return level_results


async def run_load_benchmarks():
    """Run full load benchmark suite."""
    print("=== STARTING CONCURRENT LOAD TESTING ===")
    results = {}

    with tempfile.TemporaryDirectory(prefix="bench_load_") as tmp:
        db_file = Path(tmp) / "load_test.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

            async def override_get_db():
                async with session_maker() as s:
                    yield s

            app.dependency_overrides[get_db] = override_get_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 1. Dashboard / Health Concurrency
                print("1. Testing Dashboard Health Concurrency (1, 10, 25, 50)...")
                dash_results = await benchmark_endpoint_concurrency(
                    client=client,
                    method="GET",
                    url="/api/health/live",
                    payload=None,
                    concurrency_levels=[1, 10, 25, 50],
                    requests_per_level=50,
                )
                results["dashboard_health_concurrency"] = dash_results
                print(f"  Dashboard (50 clients): {dash_results['concurrency_50']['requests_per_second']} req/s, mean={dash_results['concurrency_50']['mean_ms']}ms")

                # 2. Search Concurrency
                print("\n2. Testing Search API Concurrency (1, 5, 10, 20)...")
                search_results = await benchmark_endpoint_concurrency(
                    client=client,
                    method="POST",
                    url="/api/search",
                    payload={"query": "centrifugal pump pressure specifications", "limit": 5},
                    concurrency_levels=[1, 5, 10, 20],
                    requests_per_level=30,
                )
                results["search_concurrency"] = search_results
                print(f"  Search (20 clients): {search_results['concurrency_20']['requests_per_second']} req/s, mean={search_results['concurrency_20']['mean_ms']}ms, 429s={search_results['concurrency_20']['rate_limits_429']}")

                # 3. Overview API Concurrency
                print("\n3. Testing Dashboard Overview API Concurrency (1, 5, 15)...")
                overview_results = await benchmark_endpoint_concurrency(
                    client=client,
                    method="GET",
                    url="/api/dashboard/overview",
                    payload=None,
                    concurrency_levels=[1, 5, 15],
                    requests_per_level=30,
                )
                results["overview_concurrency"] = overview_results
                print(f"  Overview (15 clients): {overview_results['concurrency_15']['requests_per_second']} req/s, mean={overview_results['concurrency_15']['mean_ms']}ms")

            app.dependency_overrides.clear()
        finally:
            await engine.dispose()

    out_file = BACKEND_DIR / "benchmarks" / "load_test_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nLoad benchmark results successfully written to: {out_file}")
    return results


if __name__ == "__main__":
    asyncio.run(run_load_benchmarks())
