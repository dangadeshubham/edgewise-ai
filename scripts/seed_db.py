"""
EDGEWISE AI — Seed Database CLI

Loads realistic industrial maintenance fixture data into the SQLite database.
Run via:
    python scripts/seed_db.py
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path and normalize working directory to backend
backend_dir = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(backend_dir))
import os
os.chdir(backend_dir)

from app.core.database import async_session_factory
from app.services.seed.service import SeedService


async def main():
    print("Loading EDGEWISE AI fixture seed data...")
    async with async_session_factory() as session:
        service = SeedService(session)
        summary = await service.seed_all()
        print("Seed data successfully loaded:")
        for k, v in summary.items():
            print(f"  - {k}: {v} records inserted")


if __name__ == "__main__":
    asyncio.run(main())
