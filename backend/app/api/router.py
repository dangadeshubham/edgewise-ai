"""
EDGEWISE AI — API Router Registry

All API v1 routes are registered here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import documents, search, copilot, memory, sync, conflicts, devices, activity, dashboard

api_router = APIRouter(prefix="/api")

api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(copilot.router, prefix="/copilot", tags=["AI Copilot"])
api_router.include_router(memory.router, prefix="/memory", tags=["Memory"])
api_router.include_router(sync.router, prefix="/sync", tags=["Synchronization"])
api_router.include_router(conflicts.router, prefix="/conflicts", tags=["Conflicts"])
api_router.include_router(devices.router, prefix="/devices", tags=["Devices"])
api_router.include_router(activity.router, prefix="/activity", tags=["Activity"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
