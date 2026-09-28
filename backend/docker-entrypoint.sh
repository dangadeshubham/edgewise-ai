#!/bin/sh
set -e

echo "[edgewise-backend] Starting EDGEWISE AI Backend..."

# Ensure target directories exist within mounted volume
mkdir -p "${UPLOAD_DIR:-/app/data/uploads}" \
         "${PROCESSED_DIR:-/app/data/processed}" \
         "${EDGE_MUTABLE_SHARD_PATH:-/app/data/qdrant_edge/mutable}" \
         "${EDGE_IMMUTABLE_SHARD_PATH:-/app/data/qdrant_edge/immutable}" \
         /app/data/sqlite 2>/dev/null || true

# Run database migrations
echo "[edgewise-backend] Applying Alembic database migrations..."
if [ -f "/app/alembic.ini" ]; then
    alembic upgrade head || {
        echo "[edgewise-backend] WARNING: Alembic upgrade encountered an issue; proceeding with startup..."
    }
fi

echo "[edgewise-backend] Startup initialization complete. Executing command: $@"
exec "$@"
