"""Evidence corpus integrity auditor.

The provided sample data contains deliberate defects (one shared requirement
description, orphan requirement references, impossible dates, status/confidence
contradictions). OMNIS must detect and report these, never crash on them. Each
check is a pure function over the loaded records (plus the parsed requirements
for the orphan check) and returns at most one IntegrityFinding. Findings carry a
full count and a capped sample of affected ids so reports stay readable.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from omnis.freshness import REFERENCE_DATE
from omnis.models import EvidenceRecord, IntegrityFinding, Requirement

# REFERENCE_DATE is defined once in omnis.freshness (the audit "as of" date) and
# reused here so the integrity auditor and the freshness model never drift apart.
# Re-exported through this module for backward compatibility.
__all__ = ["REFERENCE_DATE", "audit_corpus"]

# How many affected ids to embed in a finding before truncating.
SAMPLE_CAP = 10
# Allowed drift, in days, between freshness_days and the computed age.
FRESHNESS_TOLERANCE_DAYS = 7


def _sample(ids: list[str]) -> list[str]:
    return ids[:SAMPLE_CAP]


def duplicate_description(records: list[EvidenceRecord]) -> IntegrityFinding | None:
    """Flag when a single requirement_description dominates the corpus (>50%)."""
    descriptions = [r.requirement_description for r in records if r.requirement_description]
    if not descriptions:
        return None
    counts = Counter(descriptions)
    value, count = counts.most_common(1)[0]
    if count <= len(descriptions) * 0.5:
        return None
    affected = [r.evidence_id for r in records if r.requirement_description == value]
    return IntegrityFinding(
        check_name="duplicate_description",
        severity="HIGH",
        affected_ids=_sample(affected),
        affected_count=count,
        description=(
            f"{count} of {len(descriptions)} rows share one requirement_description "
            f"({len(counts)} distinct values total): {value!r}. Evidence cannot be "
            f"told apart by description alone."
        ),
    )


def orphan_requirement_refs(
    records: list[EvidenceRecord], requirements: list[Requirement]
) -> IntegrityFinding | None:
    """Flag evidence whose requirement_id matches no parsed requirement."""
    known = {req.id for req in requirements}
    orphan_rows = [r for r in records if r.requirement_id not in known]
    if not orphan_rows:
        return None
    unique_orphans = sorted({r.requirement_id for r in orphan_rows})
    return IntegrityFinding(
        check_name="orphan_requirement_refs",
        severity="HIGH",
        affected_ids=_sample(unique_orphans),
        affected_count=len(orphan_rows),
        description=(
            f"{len(orphan_rows)} rows reference {len(unique_orphans)} requirement_ids "
            f"absent from the {len(known)} parsed requirements. Sample: "
            f"{', '.join(unique_orphans[:SAMPLE_CAP])}."
        ),
    )


def impossible_review_dates(records: list[EvidenceRecord]) -> IntegrityFinding | None:
    """Flag rows where review_date precedes collection_date."""
    affected = [
        r.evidence_id
        for r in records
        if r.review_date is not None
        and r.collection_date is not None
        and r.review_date < r.collection_date
    ]
    if not affected:
        return None
    return IntegrityFinding(
        check_name="impossible_review_dates",
        severity="MEDIUM",
        affected_ids=_sample(affected),
        affected_count=len(affected),
        description=(
            f"{len(affected)} rows have review_date earlier than collection_date "
            f"(evidence reviewed before it was collected)."
        ),
    )


def status_confidence_contradiction(
    records: list[EvidenceRecord],
) -> IntegrityFinding | None:
    """Flag Approved evidence carrying a confidence_score below 0.6."""
    affected = [
        r.evidence_id
        for r in records
        if r.status == "Approved"
        and r.confidence_score is not None
        and r.confidence_score < 0.6
    ]
    if not affected:
        return None
    return IntegrityFinding(
        check_name="status_confidence_contradiction",
        severity="MEDIUM",
        affected_ids=_sample(affected),
        affected_count=len(affected),
        description=(
            f"{len(affected)} rows are marked Approved but carry confidence_score "
            f"< 0.6. Status and confidence disagree."
        ),
    )


def freshness_field_consistency(
    records: list[EvidenceRecord], reference_date: date = REFERENCE_DATE
) -> IntegrityFinding | None:
    """Flag rows where freshness_days disagrees with reference_date - collection_date."""
    affected: list[str] = []
    for r in records:
        if r.collection_date is None or r.freshness_days is None:
            continue
        computed_age = (reference_date - r.collection_date).days
        if abs(r.freshness_days - computed_age) > FRESHNESS_TOLERANCE_DAYS:
            affected.append(r.evidence_id)
    if not affected:
        return None
    return IntegrityFinding(
        check_name="freshness_field_consistency",
        severity="LOW",
        affected_ids=_sample(affected),
        affected_count=len(affected),
        description=(
            f"{len(affected)} rows have a freshness_days value that disagrees with "
            f"(reference_date {reference_date.isoformat()} - collection_date) by more "
            f"than {FRESHNESS_TOLERANCE_DAYS} days. The stored freshness cannot be "
            f"trusted; OMNIS recomputes freshness from dates."
        ),
    )


def duplicate_evidence_ids(records: list[EvidenceRecord]) -> IntegrityFinding | None:
    """Flag evidence_id values that appear more than once."""
    counts = Counter(r.evidence_id for r in records)
    dupes = sorted(eid for eid, n in counts.items() if n > 1)
    if not dupes:
        return None
    total = sum(counts[eid] for eid in dupes)
    return IntegrityFinding(
        check_name="duplicate_evidence_ids",
        severity="HIGH",
        affected_ids=_sample(dupes),
        affected_count=total,
        description=(
            f"{len(dupes)} evidence_id values are not unique ({total} rows involved). "
            f"Evidence ids must be primary keys."
        ),
    )


def null_or_malformed_dates(records: list[EvidenceRecord]) -> IntegrityFinding | None:
    """Flag rows with a blank or unparseable collection_date or review_date."""
    affected: list[str] = []
    for r in records:
        if r.present_but_unparsed_dates or r.collection_date is None or r.review_date is None:
            affected.append(r.evidence_id)
    if not affected:
        return None
    return IntegrityFinding(
        check_name="null_or_malformed_dates",
        severity="LOW",
        affected_ids=_sample(affected),
        affected_count=len(affected),
        description=(
            f"{len(affected)} rows have a missing or unparseable collection_date or "
            f"review_date. Freshness and review checks skip these rows."
        ),
    )


def out_of_range_confidence(records: list[EvidenceRecord]) -> IntegrityFinding | None:
    """Flag confidence_score values outside [0.0, 1.0]."""
    affected = [
        r.evidence_id
        for r in records
        if r.confidence_score is not None and not (0.0 <= r.confidence_score <= 1.0)
    ]
    if not affected:
        return None
    return IntegrityFinding(
        check_name="out_of_range_confidence",
        severity="MEDIUM",
        affected_ids=_sample(affected),
        affected_count=len(affected),
        description=(
            f"{len(affected)} rows have a confidence_score outside the [0.0, 1.0] range."
        ),
    )


def audit_corpus(
    records: list[EvidenceRecord],
    requirements: list[Requirement],
    reference_date: date = REFERENCE_DATE,
) -> list[IntegrityFinding]:
    """Run every integrity check and return the findings that fired."""
    findings = [
        duplicate_description(records),
        orphan_requirement_refs(records, requirements),
        impossible_review_dates(records),
        status_confidence_contradiction(records),
        freshness_field_consistency(records, reference_date),
        duplicate_evidence_ids(records),
        null_or_malformed_dates(records),
        out_of_range_confidence(records),
    ]
    return [f for f in findings if f is not None]
