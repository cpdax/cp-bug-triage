"""Triage logic — evaluate which fields are missing on each bug.

Pure functions. No I/O. Takes WorkItems in, returns evaluation results.

Status thresholds (recalibrated 2026-04-30 after PM field list locked in):
  - 0 missing = 🟢 ready to advance
  - 1 missing = 🟡 partially ready
  - 2+ missing = 🔴 fully blocked
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

from config.fields import (
    DESIGN_FLAG_TAG,
    FIELD_REQUIREMENTS,
    PRIORITY_FIELD,
)
from lib.devops import WorkItem


@dataclass
class BugEvaluation:
    """The result of evaluating one bug's field completeness."""

    work_item: WorkItem
    missing_by_role: dict[str, list[str]] = field(default_factory=dict)
    needs_design: bool = False

    @property
    def total_missing(self) -> int:
        return sum(len(v) for v in self.missing_by_role.values())

    @property
    def is_blocked_on(self) -> list[str]:
        """Roles that have at least one missing field."""
        return [role for role, fields in self.missing_by_role.items() if fields]

    @property
    def status(self) -> str:
        """🟢 ready / 🟡 partial / 🔴 fully blocked.

        With 3 base required fields (PM x2, Eng x1) plus 1 conditional (Design),
        we calibrate as: 0 = ready, 1 = partial, 2+ = blocked.
        """
        n = self.total_missing
        if n == 0:
            return "ready"
        if n >= 2:
            return "blocked"
        return "partial"

    @property
    def age_days(self) -> int:
        if not self.work_item.created_date:
            return 0
        try:
            created = date_parser.isoparse(self.work_item.created_date)
            now = datetime.now(timezone.utc)
            return (now - created).days
        except (ValueError, TypeError):
            return 0

    @property
    def priority(self) -> str:
        """Priority value from DevOps (e.g., '1', '2', '3', '4'). Empty string if absent."""
        val = self.work_item.fields.get(PRIORITY_FIELD)
        if val is None or val == "":
            return ""
        return str(val)


def evaluate_bug(work_item: WorkItem) -> BugEvaluation:
    """Run the field requirements against a single work item."""
    needs_design = _has_design_tag(work_item.tags)
    missing_by_role: dict[str, list[str]] = {"pm": [], "eng": [], "design": []}

    for req in FIELD_REQUIREMENTS:
        if req["conditional"] and req["role"] == "design" and not needs_design:
            continue
        value = work_item.fields.get(req["ado_field"])
        if not _is_filled(value, req["check"]):
            missing_by_role[req["role"]].append(req["label"])

    return BugEvaluation(
        work_item=work_item,
        missing_by_role=missing_by_role,
        needs_design=needs_design,
    )


def evaluate_bugs(work_items: list[WorkItem]) -> list[BugEvaluation]:
    return [evaluate_bug(wi) for wi in work_items]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _has_design_tag(tags: list[str]) -> bool:
    """Case-insensitive check for the design flag tag."""
    target = DESIGN_FLAG_TAG.casefold()
    return any(t.casefold() == target for t in tags)


def _is_filled(value: Any, check: str) -> bool:
    """Return True if the value satisfies the check."""
    if check == "non_empty":
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return bool(value)
    if check == "non_zero":
        try:
            return value is not None and float(value) > 0
        except (TypeError, ValueError):
            return False
    return False


# -----------------------------------------------------------------------------
# Aggregation helpers — used by the renderer to build summary banners.
# -----------------------------------------------------------------------------

def summary_stats(evaluations: list[BugEvaluation]) -> dict[str, int]:
    """Compute counts for the summary banner."""
    total = len(evaluations)
    blocked = sum(1 for e in evaluations if e.status == "blocked")
    partial = sum(1 for e in evaluations if e.status == "partial")
    ready = sum(1 for e in evaluations if e.status == "ready")
    pm_holding = sum(1 for e in evaluations if "pm" in e.is_blocked_on)
    eng_holding = sum(1 for e in evaluations if "eng" in e.is_blocked_on)
    design_holding = sum(1 for e in evaluations if "design" in e.is_blocked_on)
    return {
        "total": total,
        "blocked": blocked,
        "partial": partial,
        "ready": ready,
        "pm_holding": pm_holding,
        "eng_holding": eng_holding,
        "design_holding": design_holding,
    }


def filter_by_role(
    evaluations: list[BugEvaluation], role: str
) -> list[BugEvaluation]:
    """Return only bugs blocked on the given role, sorted by age desc."""
    matching = [e for e in evaluations if role in e.is_blocked_on]
    return sorted(matching, key=lambda e: e.age_days, reverse=True)


def ready_to_advance(evaluations: list[BugEvaluation]) -> list[BugEvaluation]:
    return sorted(
        [e for e in evaluations if e.status == "ready"],
        key=lambda e: e.age_days,
        reverse=True,
    )
