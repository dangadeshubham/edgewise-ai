"""
EDGEWISE AI — Seed Database CLI

Loads realistic industrial maintenance fixture data into the SQLite database.
Run via:
    python scripts/seed_db.py
or in container:
    docker compose run --rm edgewise-backend python scripts/seed_db.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Resolve backend directory whether running from workspace root or inside container
current_dir = Path(__file__).resolve().parent
if (current_dir.parent / "backend" / "app").exists():
    backend_dir = current_dir.parent / "backend"
elif (current_dir.parent / "app").exists():
    backend_dir = current_dir.parent
elif Path("/app/app").exists():
    backend_dir = Path("/app")
else:
    backend_dir = Path.cwd()

sys.path.insert(0, str(backend_dir))
try:
    os.chdir(backend_dir)
except Exception:
    pass

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
