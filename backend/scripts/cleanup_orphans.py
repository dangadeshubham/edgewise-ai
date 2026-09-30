"""
EDGEWISE AI — Vector Shard Orphan Cleanup CLI Tool

Audits and cleans orphaned vectors from Qdrant Edge shards that have no
corresponding active record in SQLite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend root to path
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.core.database import async_session_factory
from app.services.edge_memory.cleanup import VectorCleanupService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile and cleanup orphaned Qdrant vectors.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Audit without deleting")
    parser.add_argument("--execute", action="store_true", default=False, help="Perform safe deletion")
    parser.add_argument("--shard", default="mutable", choices=["mutable", "immutable"], help="Target shard")
    parser.add_argument("--json", action="store_true", default=False, help="Output JSON format")
    args = parser.parse_args()

    is_dry_run = not args.execute

    async with async_session_factory() as session:
        service = VectorCleanupService(session)
        report = await service.reconcile_and_cleanup(dry_run=is_dry_run, shard_type=args.shard)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        mode_str = "DRY RUN (AUDIT ONLY)" if is_dry_run else "EXECUTED PURGE"
        print("=" * 60)
        print(f"EDGEWISE AI — Vector Shard Reconciliation [{mode_str}]")
        print("=" * 60)
        print(f"Shard Target:               {args.shard}")
        print(f"Total Points Scanned:       {report.total_scanned}")
        print(f"Valid Vectors Retained:     {report.valid_retained}")
        print(f"Orphans Identified:         {report.orphans_identified}")
        print(f"Orphans Deleted:            {report.orphans_deleted}")
        print(f"Remaining Mutable Points:   {report.remaining_mutable_points}")
        print(f"Remaining Immutable Points: {report.remaining_immutable_points}")
        print("\nOrphan Breakdown by Category:")
        for cat, count in report.orphan_categories.items():
            print(f"  - {cat}: {count}")
        if is_dry_run and report.orphans_identified > 0:
            print("\nTo safely purge identified orphans, run:")
            print("  python backend/scripts/cleanup_orphans.py --execute")


if __name__ == "__main__":
    asyncio.run(main())
