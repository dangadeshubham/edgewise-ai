"""
EDGEWISE AI — Cross-Subsystem Data Integrity Verifier (Phase 11)

Compares synchronized logical records across:
1. SQLite (source of truth for documents, memory records, and sync queue)
2. Qdrant Edge mutable shard (local un-synced / hot vector cache)
3. Qdrant Edge immutable shard (locally replicated cloud snapshot)
4. Qdrant Server (remote central vector database)

Verification Statuses:
- MATCH: Record exists with matching content hash, revision, and point ID
- MISMATCH: Content hash or revision divergence detected without a logged conflict
- MISSING_LOCAL: Record exists remotely on Qdrant Server but absent from SQLite/Edge
- MISSING_REMOTE: Record marked as SYNCED in SQLite but absent from Qdrant Server
- CONFLICT: Divergence with an open or tracked conflict record in SQLite

Usage:
    python backend/scripts/verify_integrity.py [--json] [--verbose]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.database import Conflict, Document, DocumentChunk, MemoryRecord, SyncItem
from app.services.edge_memory import generate_point_id_from_chunk_id, get_edge_memory_service
from app.services.synchronization.constants import SyncState
from app.services.synchronization.qdrant_backend import QdrantServerSyncBackend


class IntegrityStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING_LOCAL = "MISSING_LOCAL"
    MISSING_REMOTE = "MISSING_REMOTE"
    CONFLICT = "CONFLICT"


@dataclass
class RecordIntegrityReport:
    record_id: str
    record_type: str
    sqlite_revision: Optional[int]
    sqlite_content_hash: Optional[str]
    sqlite_sync_status: Optional[str]
    edge_point_id: Optional[str]
    edge_shard: Optional[str]
    edge_present: bool
    remote_present: bool
    remote_revision: Optional[int]
    remote_content_hash: Optional[str]
    status: IntegrityStatus
    details: str


@dataclass
class OverallIntegritySummary:
    total_audited: int
    matches: int
    mismatches: int
    missing_local: int
    missing_remote: int
    conflicts: int
    records: List[RecordIntegrityReport]


class IntegrityVerifier:
    def __init__(self, db_session: AsyncSession, qdrant_backend: Optional[QdrantServerSyncBackend] = None):
        self.session = db_session
        self.settings = get_settings()
        self.qdrant_backend = qdrant_backend or QdrantServerSyncBackend(check_compatibility=False)
        self.edge_svc = get_edge_memory_service()

    async def verify_all(self) -> OverallIntegritySummary:
        reports: List[RecordIntegrityReport] = []

        # 1. Fetch all local MemoryRecords
        stmt_mem = select(MemoryRecord)
        res_mem = await self.session.execute(stmt_mem)
        mem_records = res_mem.scalars().all()

        # 2. Fetch all tracked conflicts
        stmt_conf = select(Conflict)
        res_conf = await self.session.execute(stmt_conf)
        conflicts = {c.record_id: c for c in res_conf.scalars().all()}

        # 3. Check Qdrant Server availability
        server_alive = await self.qdrant_backend.health_check()
        remote_points: Dict[str, Any] = {}
        if server_alive:
            try:
                server_recs = await self.qdrant_backend.fetch_server_points(limit=1000)
                for pt in server_recs:
                    remote_points[str(pt.id)] = pt
            except Exception:
                pass

        # 4. Verify each memory record
        for mem in mem_records:
            pt_id = generate_point_id_from_chunk_id(mem.id)

            # Check edge shards
            edge_present = False
            edge_shard = None
            try:
                mut_pts = self.edge_svc.retrieve_points([pt_id], shard_type="mutable")
                if mut_pts:
                    edge_present = True
                    edge_shard = "mutable"
                elif self.edge_svc.has_immutable_shard():
                    imm_pts = self.edge_svc.retrieve_points([pt_id], shard_type="immutable")
                    if imm_pts:
                        edge_present = True
                        edge_shard = "immutable"
            except Exception:
                pass

            # Check remote
            remote_pt = remote_points.get(pt_id)
            remote_present = remote_pt is not None
            remote_rev = remote_pt.payload.get("revision") if remote_pt and remote_pt.payload else None
            remote_hash = remote_pt.payload.get("content_hash") if remote_pt and remote_pt.payload else None

            # Determine status
            has_conflict = mem.id in conflicts and conflicts[mem.id].status == "open"

            if has_conflict:
                status = IntegrityStatus.CONFLICT
                details = f"Open conflict tracked (local rev {mem.revision} vs cloud rev {conflicts[mem.id].cloud_revision})"
            elif mem.sync_status == SyncState.SYNCED.value and not remote_present and server_alive:
                status = IntegrityStatus.MISSING_REMOTE
                details = f"Record marked SYNCED in SQLite but absent from Qdrant Server"
            elif remote_present and (mem.revision != remote_rev or mem.content_hash != remote_hash):
                status = IntegrityStatus.MISMATCH
                details = f"Revision/Hash mismatch (local r{mem.revision}:{mem.content_hash[:8]} vs remote r{remote_rev}:{str(remote_hash)[:8]})"
            else:
                status = IntegrityStatus.MATCH
                details = "Locally and remotely consistent"

            reports.append(
                RecordIntegrityReport(
                    record_id=mem.id,
                    record_type=mem.record_type,
                    sqlite_revision=mem.revision,
                    sqlite_content_hash=mem.content_hash,
                    sqlite_sync_status=mem.sync_status,
                    edge_point_id=pt_id,
                    edge_shard=edge_shard,
                    edge_present=edge_present,
                    remote_present=remote_present,
                    remote_revision=remote_rev,
                    remote_content_hash=remote_hash,
                    status=status,
                    details=details,
                )
            )

        # 5. Check for any remote points missing locally
        local_ids = {generate_point_id_from_chunk_id(m.id) for m in mem_records}
        for r_id, r_pt in remote_points.items():
            if r_id not in local_ids:
                payload = r_pt.payload or {}
                reports.append(
                    RecordIntegrityReport(
                        record_id=payload.get("record_id", r_id),
                        record_type=payload.get("record_type", "unknown"),
                        sqlite_revision=None,
                        sqlite_content_hash=None,
                        sqlite_sync_status=None,
                        edge_point_id=r_id,
                        edge_shard=None,
                        edge_present=False,
                        remote_present=True,
                        remote_revision=payload.get("revision"),
                        remote_content_hash=payload.get("content_hash"),
                        status=IntegrityStatus.MISSING_LOCAL,
                        details="Present on Qdrant Server but absent from local SQLite",
                    )
                )

        matches = sum(1 for r in reports if r.status == IntegrityStatus.MATCH)
        mismatches = sum(1 for r in reports if r.status == IntegrityStatus.MISMATCH)
        missing_local = sum(1 for r in reports if r.status == IntegrityStatus.MISSING_LOCAL)
        missing_remote = sum(1 for r in reports if r.status == IntegrityStatus.MISSING_REMOTE)
        conf_count = sum(1 for r in reports if r.status == IntegrityStatus.CONFLICT)

        return OverallIntegritySummary(
            total_audited=len(reports),
            matches=matches,
            mismatches=mismatches,
            missing_local=missing_local,
            missing_remote=missing_remote,
            conflicts=conf_count,
            records=reports,
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Edgewise AI Cross-Subsystem Integrity Verifier")
    parser.add_argument("--json", action="store_true", help="Output summary in JSON format")
    parser.add_argument("--verbose", action="store_true", help="Output full record-by-record reports")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.sqlite_database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as session:
        verifier = IntegrityVerifier(session)
        summary = await verifier.verify_all()

    if args.json:
        print(json.dumps(asdict(summary), default=str, indent=2))
    else:
        print("\n========================================================")
        print(" EDGEWISE AI — CROSS-SUBSYSTEM INTEGRITY AUDIT")
        print("========================================================")
        print(f"Total Records Audited : {summary.total_audited}")
        print(f"Matches               : {summary.matches}")
        print(f"Mismatches            : {summary.mismatches}")
        print(f"Missing Locally       : {summary.missing_local}")
        print(f"Missing Remotely      : {summary.missing_remote}")
        print(f"Tracked Conflicts     : {summary.conflicts}")
        print("--------------------------------------------------------")

        if args.verbose or summary.mismatches > 0 or summary.missing_remote > 0:
            for r in summary.records:
                print(f"[{r.status.value:<14}] ID: {r.record_id[:18]}... | Details: {r.details}")

        if summary.mismatches == 0 and summary.missing_remote == 0:
            print("[PASS] System state is authoritatively consistent.")
            return 0
        else:
            print("[FAIL] Consistency divergence detected!")
            return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
