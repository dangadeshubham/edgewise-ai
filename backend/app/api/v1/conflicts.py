"""
EDGEWISE AI — Conflict Management API (Phase 8)

Endpoints:
- GET  /api/conflicts             List conflicts with status/device/date filters and counts
- GET  /api/conflicts/{id}        Get conflict detail with side-by-side diff
- POST /api/conflicts/{id}/claim  Claim a conflict (transitions OPEN -> IN_REVIEW)
- POST /api/conflicts/{id}/resolve Resolve conflict (keep_local, keep_cloud, merge, manual)
- POST /api/conflicts/{id}/dismiss Dismiss conflict
- POST /api/conflicts/{id}/suggest-merge Generate non-autonomous merge suggestion
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.database import Conflict
from app.schemas.api import (
    ConflictClaimRequest,
    ConflictDiffDetailResponse,
    ConflictDiffLineResponse,
    ConflictDismissRequest,
    ConflictFieldDiffResponse,
    ConflictListResponse,
    ConflictResolveRequest,
    ConflictResponse,
    ConflictSuggestMergeResponse,
)
from app.services.conflict.constants import (
    ConflictConcurrencyError,
    ConflictNotFoundError,
    ConflictResolutionType,
    ConflictState,
    ConflictStateError,
    ConflictValidationError,
)
from app.services.conflict.service import ConflictService

router = APIRouter()


@router.get("", response_model=ConflictListResponse)
async def list_conflicts(
    status_filter: Optional[str] = Query(None, alias="status"),
    device_id: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    sort_by: str = Query("newest", pattern="^(newest|oldest_unresolved)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List conflicts with filtering, ordering, and total status counts."""
    service = ConflictService(db)
    items, total = await service.list_conflicts(
        status=status_filter,
        device_id=device_id,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )

    # Compute breakdown counts for UI tabs
    counts_stmt = select(Conflict.status, func.count(Conflict.id)).group_by(Conflict.status)
    counts_res = await db.execute(counts_stmt)
    counts_map = dict(counts_res.all())

    return ConflictListResponse(
        items=[ConflictResponse.model_validate(c) for c in items],
        total=total,
        open_count=counts_map.get(ConflictState.OPEN.value, 0),
        in_review_count=counts_map.get(ConflictState.IN_REVIEW.value, 0),
        resolved_count=counts_map.get(ConflictState.RESOLVED.value, 0),
        dismissed_count=counts_map.get(ConflictState.DISMISSED.value, 0),
    )


@router.get("/{conflict_id}", response_model=ConflictDiffDetailResponse)
async def get_conflict(
    conflict_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full conflict details along with side-by-side diff."""
    service = ConflictService(db)
    try:
        conflict, diff = await service.get_conflict_with_diff(conflict_id)
    except ConflictNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return ConflictDiffDetailResponse(
        conflict=ConflictResponse.model_validate(conflict),
        lines=[
            ConflictDiffLineResponse(
                line_number_local=line.line_number_local,
                line_number_cloud=line.line_number_cloud,
                line_type=line.line_type,
                content=line.content,
            )
            for line in diff.lines
        ],
        metadata_diffs=[
            ConflictFieldDiffResponse(
                field_name=md.field_name,
                local_value=md.local_value,
                cloud_value=md.cloud_value,
                is_different=md.is_different,
            )
            for md in diff.metadata_diffs
        ],
        json_field_diffs=[
            ConflictFieldDiffResponse(
                field_name=jd.field_name,
                local_value=jd.local_value,
                cloud_value=jd.cloud_value,
                is_different=jd.is_different,
            )
            for jd in (diff.json_field_diffs or [])
        ]
        if diff.json_field_diffs is not None
        else None,
        additions_count=diff.additions_count,
        deletions_count=diff.deletions_count,
        unchanged_count=diff.unchanged_count,
        is_identical=diff.is_identical,
    )


@router.post("/{conflict_id}/claim", response_model=ConflictResponse)
async def claim_conflict(
    conflict_id: str,
    body: ConflictClaimRequest,
    db: AsyncSession = Depends(get_db),
):
    """Claim a conflict for review (transitions OPEN -> IN_REVIEW)."""
    service = ConflictService(db)
    try:
        conflict = await service.claim_conflict(
            conflict_id=conflict_id,
            claimed_by=body.claimed_by,
            expected_version=body.expected_version,
        )
        await db.commit()
        return ConflictResponse.model_validate(conflict)
    except ConflictNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictConcurrencyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ConflictStateError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{conflict_id}/resolve", response_model=ConflictResponse)
async def resolve_conflict(
    conflict_id: str,
    body: ConflictResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Resolve a conflict explicitly:
    - keep_local
    - keep_cloud
    - merge (requires merged_content)
    - manual (requires manual_content or merged_content)
    """
    res_type = body.resolution.lower()
    valid_types = [
        ConflictResolutionType.KEEP_LOCAL.value,
        ConflictResolutionType.KEEP_CLOUD.value,
        ConflictResolutionType.MERGE.value,
        ConflictResolutionType.MANUAL.value,
    ]
    if res_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid resolution type '{body.resolution}'. Must be one of: {valid_types}",
        )

    service = ConflictService(db)
    try:
        if res_type == ConflictResolutionType.KEEP_LOCAL.value:
            conflict = await service.resolve_keep_local(
                conflict_id=conflict_id,
                resolved_by=body.resolved_by,
                notes=body.notes,
                expected_version=body.expected_version,
            )
        elif res_type == ConflictResolutionType.KEEP_CLOUD.value:
            conflict = await service.resolve_keep_cloud(
                conflict_id=conflict_id,
                resolved_by=body.resolved_by,
                notes=body.notes,
                expected_version=body.expected_version,
            )
        elif res_type == ConflictResolutionType.MERGE.value:
            content = body.merged_content or body.manual_content
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="merged_content is required for resolution type 'merge'.",
                )
            conflict = await service.resolve_merge(
                conflict_id=conflict_id,
                merged_content=content,
                resolved_by=body.resolved_by,
                notes=body.notes,
                expected_version=body.expected_version,
            )
        elif res_type == ConflictResolutionType.MANUAL.value:
            content = body.manual_content or body.merged_content
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="manual_content is required for resolution type 'manual'.",
                )
            conflict = await service.resolve_manual(
                conflict_id=conflict_id,
                manual_content=content,
                resolved_by=body.resolved_by,
                notes=body.notes,
                expected_version=body.expected_version,
            )

        await db.commit()
        return ConflictResponse.model_validate(conflict)

    except ConflictNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictConcurrencyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (ConflictStateError, ConflictValidationError) as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{conflict_id}/dismiss", response_model=ConflictResponse)
async def dismiss_conflict(
    conflict_id: str,
    body: ConflictDismissRequest,
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a conflict without modifying local or cloud content."""
    service = ConflictService(db)
    try:
        conflict = await service.dismiss_conflict(
            conflict_id=conflict_id,
            dismissed_by=body.dismissed_by,
            reason=body.reason,
            expected_version=body.expected_version,
        )
        await db.commit()
        return ConflictResponse.model_validate(conflict)
    except ConflictNotFoundError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConflictConcurrencyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ConflictStateError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{conflict_id}/suggest-merge", response_model=ConflictSuggestMergeResponse)
async def suggest_merge(
    conflict_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an unapproved merge suggestion for user review.
    Does NOT publish or save to database.
    """
    service = ConflictService(db)
    try:
        suggestion = await service.generate_suggested_merge(conflict_id)
        return ConflictSuggestMergeResponse(**suggestion)
    except ConflictNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
