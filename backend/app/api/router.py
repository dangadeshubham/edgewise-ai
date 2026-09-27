"""
EDGEWISE AI — API Router Registry

All API v1 routes are registered here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import documents, search, copilot, memory, sync, conflicts, devices, activity, dashboard

api_router = APIRouter(prefix="/api")
v1_router = APIRouter(prefix="/v1")

routers = [
    (documents.router, "/documents", ["Documents"]),
    (search.router, "/search", ["Search"]),
    (copilot.router, "/copilot", ["AI Copilot"]),
    (memory.router, "/memory", ["Memory"]),
    (sync.router, "/sync", ["Synchronization"]),
    (conflicts.router, "/conflicts", ["Conflicts"]),
    (devices.router, "/devices", ["Devices"]),
    (activity.router, "/activity", ["Activity"]),
    (dashboard.router, "/dashboard", ["Dashboard"]),
]

for r_obj, prefix, tags in routers:
    api_router.include_router(r_obj, prefix=prefix, tags=tags)
    v1_router.include_router(r_obj, prefix=prefix, tags=tags)

api_router.include_router(v1_router)
