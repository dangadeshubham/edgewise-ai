"""
EDGEWISE AI — Minimal Qdrant Edge Proof Test

Proves the complete lifecycle of local embedded Qdrant Edge storage:
CREATE -> WRITE VECTOR -> QUERY -> RETRIEVE -> INFO -> FLUSH -> CLOSE -> LOAD FROM DISK -> QUERY AGAIN
"""

import shutil
import tempfile
from pathlib import Path
import pytest
import qdrant_edge


def test_qdrant_edge_lifecycle_proof():
    """
    Mandatory proof test demonstrating full Qdrant Edge lifecycle with persistence.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="qdrant_edge_proof_"))
    try:
        # 1. CREATE
        params = qdrant_edge.EdgeVectorParams(
            size=4,
            distance=qdrant_edge.Distance.Cosine,
        )
        config = qdrant_edge.EdgeConfig(vectors=params)
        shard = qdrant_edge.EdgeShard.create(str(tmp_dir), config)
        assert shard is not None

        # 2. WRITE VECTOR
        point_id = 101
        sample_vector = [0.2, 0.4, 0.6, 0.8]
        sample_payload = {
            "document_id": "doc-uuid-1",
            "filename": "centrifugal_pump_manual.txt",
            "text": "Check pump bearing temperature every 24 hours.",
        }
        point = qdrant_edge.Point(id=point_id, vector=sample_vector, payload=sample_payload)
        shard.update(qdrant_edge.UpdateOperation.upsert_points([point]))

        # 3. QUERY
        query_vector = [0.2, 0.4, 0.6, 0.8]
        query_req = qdrant_edge.QueryRequest(
            limit=5,
            query=qdrant_edge.Query.Nearest(query_vector),
            with_payload=True,
            with_vector=True,
        )
        results = shard.query(query_req)
        assert len(results) == 1
        assert results[0].id == point_id
        assert results[0].score >= 0.99
        assert results[0].payload is not None
        assert results[0].payload["filename"] == "centrifugal_pump_manual.txt"

        # 4. RETRIEVE
        retrieved = shard.retrieve([point_id], with_payload=True, with_vector=True)
        assert len(retrieved) == 1
        assert retrieved[0].id == point_id
        assert retrieved[0].payload is not None
        assert retrieved[0].payload["document_id"] == "doc-uuid-1"

        # 5. INFO
        info = shard.info()
        assert info.points_count == 1

        # 6. FLUSH
        shard.flush()

        # 7. CLOSE
        shard.close()

        # 8. LOAD FROM DISK
        reloaded_shard = qdrant_edge.EdgeShard.load(str(tmp_dir))
        assert reloaded_shard is not None

        # 9. QUERY AGAIN (Persisted Query Verification)
        reloaded_results = reloaded_shard.query(query_req)
        assert len(reloaded_results) == 1
        assert reloaded_results[0].id == point_id
        assert reloaded_results[0].score >= 0.99
        assert reloaded_results[0].payload is not None
        assert reloaded_results[0].payload["text"] == "Check pump bearing temperature every 24 hours."

        reloaded_info = reloaded_shard.info()
        assert reloaded_info.points_count == 1

        reloaded_shard.close()

    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
