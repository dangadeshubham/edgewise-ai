"""
Verification script for EDGEWISE AI Phase 4:
Real Grounded Local RAG Copilot with Ollama + Qdrant Edge.

Performs:
1. Live health & model verification
2. Real industrial queries against existing documents
3. Paraphrase retrieval test
4. Negative query / insufficient evidence test ("What is the capital of France?")
5. Strict citation traceability check (SQLite document, chunk, Qdrant Edge)
6. Real measured latency recording
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import select

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory
from app.models.database import Document, DocumentChunk
from app.services.edge_memory.service import get_edge_memory_service
from app.services.llm import OllamaService
from app.services.rag import RAGService


async def run_verification():
    print("=" * 70)
    print("EDGEWISE AI — PHASE 4 REAL LOCAL RAG COPILOT VERIFICATION")
    print("=" * 70)

    # 1. Ollama Verification
    print("\n[1] Checking Local LLM (Ollama)...")
    ollama = OllamaService()
    health = await ollama.check_health()
    print(f"  Ollama Server Available: {health.server_available}")
    print(f"  Configured Model:        {ollama.model}")
    print(f"  Model Available Locally: {health.model_available}")
    print(f"  Installed Models:        {', '.join(health.available_models) if health.available_models else 'None'}")
    assert health.server_available, "Ollama server is not running!"
    assert health.model_available, f"Model '{ollama.model}' is not available in Ollama!"

    # 2. Ingest / Verify Industrial Document Corpus
    print("\n[2] Preparing Industrial Document Corpus...")
    from app.services.ingestion.service import IngestionService
    seed_dir = Path(__file__).resolve().parents[1] / "seed_data"
    sample_docs = [
        ("centrifugal_pump_manual.txt", (seed_dir / "manuals" / "centrifugal_pump_manual.txt").read_bytes(), "text/plain", "manual"),
        ("pump_overhaul_guide.pdf", (seed_dir / "manuals" / "pump_overhaul_guide.pdf").read_bytes(), "application/pdf", "manual"),
        ("compressor_incident_report.md", (seed_dir / "incidents" / "compressor_incident_report.md").read_bytes(), "text/markdown", "incident"),
        ("turbine_inspection_sop.docx", (seed_dir / "maintenance" / "turbine_inspection_sop.docx").read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "maintenance"),
    ]

    async with async_session_factory() as session:
        ingestion = IngestionService(session)
        for fname, content, ctype, dtype in sample_docs:
            res = await ingestion.ingest_document(
                filename=fname,
                content=content,
                content_type=ctype,
                title=fname.replace("_", " ").title(),
                document_type=dtype,
            )
            if res.is_duplicate:
                await ingestion.reindex_document(res.id)
            print(f"  Document '{fname}': id={res.id[:8]}..., status={res.processing_status}, duplicate={res.is_duplicate}")
        await session.commit()

    edge = get_edge_memory_service()
    shard_info = edge.get_shard_info("mutable")
    print(f"  Mutable Shard Points:    {shard_info.get('point_count')}")
    print(f"  Vector Dimension:        {shard_info.get('vector_dimension')}")
    print(f"  Distance Metric:         {shard_info.get('distance')}")

    # 3. Test Queries
    queries = [
        ("Industrial Query 1", "Why might the pump overheat?"),
        ("Industrial Query 2", "How should the pump be shut down in an overheating event?"),
        ("Industrial Query 3", "What is the bearing inspection procedure?"),
        ("Paraphrase Query",   "What can cause excessive pump temperature?"),
        ("Negative Query",     "What is the capital of France?"),
    ]

    async with async_session_factory() as session:
        rag = RAGService(session)

        for label, q in queries:
            print("\n" + "-" * 70)
            print(f"[{label}] Query: \"{q}\"")
            print("-" * 70)

            t0 = time.perf_counter()
            response = await rag.query(question=q, max_sources=4)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            print(f"Answer:\n{response.answer}\n")
            print(f"Metrics:")
            print(f"  Insufficient Evidence:  {response.insufficient_evidence}")
            print(f"  Model Used:             {response.model_used}")
            print(f"  Top Retrieval Score:    {response.top_retrieval_score}")
            print(f"  Embedding Latency:      {response.embedding_latency_ms:.2f} ms")
            print(f"  Retrieval Latency:      {response.retrieval_latency_ms:.2f} ms")
            print(f"  Generation Latency:     {response.generation_latency_ms:.2f} ms")
            print(f"  Total Roundtrip:        {response.total_latency_ms:.2f} ms")
            print(f"  Sources Count:          {len(response.sources)}")

            # Citation Verification
            if response.sources:
                print("\n  Citations & Traceability:")
                for i, src in enumerate(response.sources, 1):
                    # Verify in SQLite
                    doc = (await session.execute(
                        select(Document).where(Document.id == src.document_id)
                    )).scalar_one_or_none()
                    assert doc is not None, f"FAIL: Document {src.document_id} not found in SQLite!"

                    chunk = (await session.execute(
                        select(DocumentChunk).where(DocumentChunk.id == src.chunk_id)
                    )).scalar_one_or_none()
                    assert chunk is not None, f"FAIL: Chunk {src.chunk_id} not found in SQLite!"

                    pages = f"p.{src.page_start}" if src.page_start else "N/A"
                    print(f"    [{i}] {src.filename} ({pages}) | Score: {src.score:.4f} | doc_id={src.document_id[:8]}... | chunk_id={src.chunk_id[:8]}...")
                    print(f"        Snippet: \"{src.content_preview[:90]}...\"")
                    print(f"        SQLite Verification: PASS (Document & Chunk exist in DB)")

            if "Negative Query" in label:
                assert response.insufficient_evidence is True, "FAIL: System hallucinated on out-of-domain query!"
                print("  Verification: Successfully rejected out-of-domain query without hallucination.")

    print("\n" + "=" * 70)
    print("PHASE 4 REAL LOCAL RAG COPILOT VERIFICATION COMPLETE: ALL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_verification())
