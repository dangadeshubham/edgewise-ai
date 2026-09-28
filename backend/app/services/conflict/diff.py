"""
EDGEWISE AI — Side-by-Side Diff Engine
Provides deterministic text and structured field difference calculation for conflicts.
"""

from __future__ import annotations

import difflib
import json
from typing import Any, Optional
from pydantic import BaseModel, Field


class DiffLine(BaseModel):
    """Represents a single line comparison in a side-by-side diff."""
    line_number_local: Optional[int] = None
    line_number_cloud: Optional[int] = None
    line_type: str = Field(description="added, removed, unchanged, or modified")
    content: str


class FieldDiff(BaseModel):
    """Represents a structured difference between a metadata or JSON field."""
    field_name: str
    local_value: Any
    cloud_value: Any
    is_different: bool


class ConflictDiffResult(BaseModel):
    """Full side-by-side diff result between local and cloud versions."""
    lines: list[DiffLine]
    metadata_diffs: list[FieldDiff]
    json_field_diffs: Optional[list[FieldDiff]] = None
    additions_count: int = 0
    deletions_count: int = 0
    unchanged_count: int = 0
    is_identical: bool = False


class DiffEngine:
    """Calculates granular line-by-line and structured field differences."""

    @staticmethod
    def compute_diff(
        local_content: str,
        cloud_content: str,
        local_meta: Optional[dict[str, Any]] = None,
        cloud_meta: Optional[dict[str, Any]] = None,
    ) -> ConflictDiffResult:
        """Compute side-by-side line diff and metadata comparisons."""
        local_lines = (local_content or "").splitlines(keepends=False)
        cloud_lines = (cloud_content or "").splitlines(keepends=False)

        differ = difflib.Differ()
        diff_generator = differ.compare(local_lines, cloud_lines)

        lines: list[DiffLine] = []
        loc_idx = 1
        cld_idx = 1
        adds = 0
        dels = 0
        unchanged = 0

        for line in diff_generator:
            code = line[:2]
            text = line[2:]

            if code == "  ":
                # Unchanged line
                lines.append(
                    DiffLine(
                        line_number_local=loc_idx,
                        line_number_cloud=cld_idx,
                        line_type="unchanged",
                        content=text,
                    )
                )
                loc_idx += 1
                cld_idx += 1
                unchanged += 1
            elif code == "- ":
                # Line present in local but removed in cloud (or modified)
                lines.append(
                    DiffLine(
                        line_number_local=loc_idx,
                        line_number_cloud=None,
                        line_type="removed",
                        content=text,
                    )
                )
                loc_idx += 1
                dels += 1
            elif code == "+ ":
                # Line added in cloud
                lines.append(
                    DiffLine(
                        line_number_local=None,
                        line_number_cloud=cld_idx,
                        line_type="added",
                        content=text,
                    )
                )
                cld_idx += 1
                adds += 1
            elif code == "? ":
                # Intra-line guide line from difflib, skip in presentation
                continue

        # Metadata comparisons
        metadata_diffs: list[FieldDiff] = []
        if local_meta or cloud_meta:
            local_meta = local_meta or {}
            cloud_meta = cloud_meta or {}
            all_keys = set(local_meta.keys()) | set(cloud_meta.keys())
            for k in sorted(all_keys):
                lv = local_meta.get(k)
                cv = cloud_meta.get(k)
                metadata_diffs.append(
                    FieldDiff(
                        field_name=k,
                        local_value=lv,
                        cloud_value=cv,
                        is_different=(lv != cv),
                    )
                )

        # JSON structured comparison if content parses as JSON on both sides
        json_field_diffs: Optional[list[FieldDiff]] = None
        try:
            local_json = json.loads(local_content)
            cloud_json = json.loads(cloud_content)
            if isinstance(local_json, dict) and isinstance(cloud_json, dict):
                json_field_diffs = []
                json_keys = set(local_json.keys()) | set(cloud_json.keys())
                for jk in sorted(json_keys):
                    ljv = local_json.get(jk)
                    cjv = cloud_json.get(jk)
                    json_field_diffs.append(
                        FieldDiff(
                            field_name=jk,
                            local_value=ljv,
                            cloud_value=cjv,
                            is_different=(ljv != cjv),
                        )
                    )
        except Exception:
            pass

        return ConflictDiffResult(
            lines=lines,
            metadata_diffs=metadata_diffs,
            json_field_diffs=json_field_diffs,
            additions_count=adds,
            deletions_count=dels,
            unchanged_count=unchanged,
            is_identical=(adds == 0 and dels == 0),
        )
