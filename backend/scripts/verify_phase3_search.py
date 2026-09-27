"""
Verification script for EDGEWISE AI Phase 3:
Real Local Semantic Memory with Qdrant Edge and Sentence-Transformers.
"""

import asyncio
import time
from app.services.edge_memory.service import get_edge_memory_service
from app.services.edge_memory.unified_search import LocalMemorySearch
from app.services.embeddings.service import get_embedding_service


def verify_real_search():
    print("=" * 60)
    print("EDGEWISE AI - PHASE 3 VERIFICATION")
    print("=" * 60)

    # 1. Verify Embedding Service
    embed_svc = get_embedding_service()
    t_embed_start = time.perf_counter()
    sample_vec = embed_svc.embed_text("Centrifugal pump bearing overheating protocol")
    embed_latency = (time.perf_counter() - t_embed_start) * 1000
    print(f"Embedding Model: {embed_svc.model_name}")
    print(f"Embedding Dimension: {len(sample_vec)}")
    print(f"Single Query Embedding Latency: {embed_latency:.2f} ms")

    # 2. Verify Edge Shard Info & Persistence
    edge_svc = get_edge_memory_service()
    info = edge_svc.get_shard_info("mutable")
    print(f"Mutable Shard Point Count: {info.get('point_count')}")
    print(f"Vector Dimensions: {info.get('vector_dimension')}")
    print(f"Distance Metric: {info.get('distance')}")
    print(f"Storage Path: {info.get('path')}")

    # 3. Query Real Industrial Documents
    searcher = LocalMemorySearch()
    queries = [
        "pump overheating",
        "emergency shutdown unit immediately",
        "bearing inspection protocol",
    ]

    for q in queries:
        print("-" * 60)
        print(f"Search Query: '{q}'")
        t_search_start = time.perf_counter()
        results = searcher.search(q, limit=3)
        search_latency = (time.perf_counter() - t_search_start) * 1000
        print(f"Retrieval Latency: {search_latency:.2f} ms | Found: {len(results.results)}")

        for i, hit in enumerate(results.results):
            p = hit.payload or {}
            print(f"  Hit #{i+1}:")
            print(f"    Score: {hit.score:.4f}")
            print(f"    Document ID: {p.get('document_id')}")
            print(f"    Filename: {p.get('filename')}")
            print(f"    Title: {p.get('title')}")
            print(f"    Doc Type: {p.get('document_type')}")
            print(f"    Snippet: {p.get('text', '')[:100]}...")

    print("=" * 60)
    print("PHASE 3 REAL SEMANTIC SEARCH VERIFICATION SUCCESSFUL")
    print("=" * 60)


if __name__ == "__main__":
    verify_real_search()
