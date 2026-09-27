"""
EDGEWISE AI — Qdrant Edge Payload Filtering Helpers

Translates API query filters into native Qdrant Edge FieldCondition and Filter objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence
import qdrant_edge


def build_payload_filter(
    device_filter: Optional[Sequence[str]] = None,
    source_filter: Optional[Sequence[str]] = None,
    document_type_filter: Optional[Sequence[str]] = None,
    sensitivity_filter: Optional[Sequence[str]] = None,
    document_id_filter: Optional[Sequence[str]] = None,
    date_from: Optional[datetime | str] = None,
    date_to: Optional[datetime | str] = None,
    must_conditions: Optional[list[Any]] = None,
) -> Optional[qdrant_edge.Filter]:
    """
    Construct native Qdrant Edge Filter using FieldConditions.
    Returns None if no filters are applied.
    """
    conditions: list[qdrant_edge.FieldCondition] = list(must_conditions or [])

    def add_match_condition(key: str, values: Optional[Sequence[str]]) -> None:
        if not values:
            return
        clean_values = [str(v).strip() for v in values if str(v).strip()]
        if not clean_values:
            return
        if len(clean_values) == 1:
            conditions.append(
                qdrant_edge.FieldCondition(
                    key=key,
                    match=qdrant_edge.MatchValue(clean_values[0]),
                )
            )
        else:
            conditions.append(
                qdrant_edge.FieldCondition(
                    key=key,
                    match=qdrant_edge.MatchAny(clean_values),
                )
            )

    add_match_condition("device_id", device_filter)
    add_match_condition("source_id", source_filter)
    add_match_condition("document_type", document_type_filter)
    add_match_condition("sensitivity", sensitivity_filter)
    add_match_condition("document_id", document_id_filter)

    # Date range condition on created_at
    if date_from or date_to:
        gte_str = date_from.isoformat() if isinstance(date_from, datetime) else date_from
        lte_str = date_to.isoformat() if isinstance(date_to, datetime) else date_to
        range_cond = qdrant_edge.RangeDateTime(gte=gte_str, lte=lte_str)
        conditions.append(
            qdrant_edge.FieldCondition(
                key="created_at",
                range=range_cond,
            )
        )

    if not conditions:
        return None

    return qdrant_edge.Filter(must=conditions)
